"""Synchronized multi-camera recording.

How sync works
--------------
One *clock thread* ticks exactly 20 times per second, scheduled on absolute
times (t0 + k/20) so it never drifts. On every tick it takes the newest frame
from *every* camera in the session and hands it to that camera's encoder.
Therefore:

* every video starts on the same tick and stops on the same tick, so all
  videos in a session have exactly the same number of frames;
* frame k of every video was captured within one camera-frame interval of
  the same moment (well inside the 50 ms tolerance);
* if a camera has not delivered a new frame since the previous tick (a
  dropped frame), the previous frame is written again so the video's timing
  stays true to real time. These *repeated* frames are counted, listed in the
  per-camera timestamp CSV, and reported at the end of the trial.

Crash safety
------------
Videos are first written as fragmented MP4 ("*.recording.mp4"), which stays
playable up to the last second even if the PC crashes or loses power. When
the recording finishes normally, the file is rewritten (without re-encoding)
as a standard MP4 with an exact frame count, which DeepLabCut and ezTrack
expect.
"""

from __future__ import annotations

import csv
import queue
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from creature_capture import ffmpeg_util
from creature_capture.camera import CameraWorker
from creature_capture.config import OUTPUT_FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH


def name_slug(name: str, default: str = "x") -> str:
    """Arena or camera label as used in file names and info files: letters,
    digits and "-" only (metadata standard: no spaces or "_", so names split
    reliably)."""
    return re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-") or default


def arena_slug(name: str) -> str:
    return name_slug(name, "Arena")


def camera_label(label: str, arena: str) -> str:
    """The camera part of a job label. Labels are unique within an experiment,
    so some include their arena ("Arena1_Overhead"); strip it so the video is
    named <date>_<time>_<arena>_<camera label>.mp4 without repeating it."""
    for prefix in (arena + "_", arena_slug(arena) + "_"):
        if label.startswith(prefix) and len(label) > len(prefix):
            label = label[len(prefix):]
            break
    return name_slug(label, "Camera")


def format_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def draw_overlay(frame: np.ndarray, index: int, fps: int, repeated: bool, cfg: dict) -> np.ndarray:
    """Burn elapsed time / frame number / fps into the top-left corner."""
    parts = []
    if cfg.get("show_elapsed", True):
        parts.append(format_elapsed(index / fps))
    if cfg.get("show_frame", True):
        parts.append(f"F{index:06d}")
    if cfg.get("show_fps", True):
        parts.append(f"{fps} fps")
    if repeated and cfg.get("mark_repeats", True):
        parts.append("*")
    if not parts:
        return frame
    text = "  ".join(parts)
    scale = float(cfg.get("font_scale", 0.5))
    font = cv2.FONT_HERSHEY_SIMPLEX
    (_, th), _ = cv2.getTextSize(text, font, scale, 1)
    org = (6, 6 + th)
    out = frame.copy()
    # Dark outline under white text: readable on any background.
    cv2.putText(out, text, org, font, scale, 0, 3, cv2.LINE_AA)
    cv2.putText(out, text, org, font, scale, 255, 1, cv2.LINE_AA)
    return out


@dataclass
class CameraJob:
    label: str  # e.g. "Arena1_Overhead" - used in the filename
    arena: str  # e.g. "Arena1"
    slot_id: str
    worker: CameraWorker


@dataclass
class CameraResult:
    label: str
    arena: str
    slot_id: str
    video: Path | None = None
    timestamps: Path | None = None
    frames: int = 0
    repeated: int = 0
    repeated_frames: list[int] = field(default_factory=list)
    verified_frames: int | None = None
    fps_measured: float | None = None  # from the clock's own tick times
    error: str = ""


class _VideoWriter:
    """One FFmpeg process + feeding thread per camera."""

    def __init__(self, base: Path, encoder: str, quality: int, overlay: dict):
        # base = output path without extension
        self.partial = base.with_name(base.name + ffmpeg_util.RECORDING_SUFFIX)
        self.final = base.with_name(base.name + ".mp4")
        self.ts_path = base.with_name(base.name + "_frames.csv")
        self.log_path = base.with_name(base.name + ".ffmpeg.log")
        self.overlay = overlay
        self.error = ""
        self._dead = False  # encoder stopped: further frames are discarded
        self.q: queue.Queue = queue.Queue(maxsize=OUTPUT_FPS * 30)
        cmd = [
            ffmpeg_util.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
            "-r", str(OUTPUT_FPS), "-i", "-",
            *ffmpeg_util.encoder_args(encoder, quality, OUTPUT_FPS),
            "-pix_fmt", "yuv420p", "-r", str(OUTPUT_FPS),
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4", str(self.partial),
        ]
        self._log = open(self.log_path, "wb")
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log,
                creationflags=ffmpeg_util.NO_WINDOW,
            )
        except OSError:
            self._log.close()
            self.log_path.unlink(missing_ok=True)
            raise
        self._ts_file = open(self.ts_path, "w", newline="", encoding="utf-8")
        self._ts = csv.writer(self._ts_file)
        self._ts.writerow(["frame", "video_time_s", "tick_time_s", "camera_frame_time_s",
                           "camera_frame_seq", "repeated"])
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"enc-{base.name}")
        self.thread.start()

    def put(self, item) -> None:
        """Queue one frame without ever blocking the clock. A frame is dropped
        (and reported) only if the encoder has stopped or is 30 s behind."""
        if self._dead:
            return
        try:
            self.q.put_nowait(item)
        except queue.Full:
            self.error = "Encoder could not keep up (queue full)"

    def _run(self) -> None:
        blank = np.zeros((OUTPUT_HEIGHT, OUTPUT_WIDTH), np.uint8)
        while True:
            item = self.q.get()
            if item is None:
                break
            frame, idx, repeated, tick_t, cam_t, seq = item
            if frame is None:
                frame = blank
            if self.overlay.get("enabled", True):
                frame = draw_overlay(frame, idx, OUTPUT_FPS, repeated, self.overlay)
            try:
                self.proc.stdin.write(np.ascontiguousarray(frame))  # no extra copy
            except (BrokenPipeError, OSError, ValueError):
                self.error = "Encoder stopped unexpectedly (see .ffmpeg.log)"
                self._dead = True
                break
            self._ts.writerow([idx, f"{idx / OUTPUT_FPS:.3f}", f"{tick_t:.4f}",
                               f"{cam_t:.4f}" if cam_t is not None else "", seq,
                               "true" if repeated else "false"])
            if idx % OUTPUT_FPS == 0:
                self._ts_file.flush()  # like the video: at most ~1 s lost in a crash
        # Free any frames still queued after an error.
        while self._dead:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def finish(self) -> None:
        self.q.put(None)
        self.thread.join()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.error = self.error or "Encoder did not finish in time"
        self._ts_file.close()
        self._log.close()
        if self.proc.returncode not in (0, None) and not self.error:
            self.error = f"Encoder exited with code {self.proc.returncode} (see .ffmpeg.log)"
        try:
            if self.log_path.stat().st_size == 0:
                self.log_path.unlink()
        except OSError:
            pass

    def abort(self) -> None:
        """Stop and remove everything (the recording never started)."""
        self.proc.kill()
        self.finish()
        for p in (self.partial, self.ts_path, self.log_path):
            p.unlink(missing_ok=True)


def _sleep_until(target: float) -> None:
    while True:
        rem = target - time.perf_counter()
        if rem <= 0:
            return
        if rem > 0.003:
            time.sleep(rem - 0.002)
        # else: spin for the final ~2 ms for accurate ticks


class RecordingSession:
    """Records a set of cameras with a shared start, stop and frame clock."""

    def __init__(
        self,
        jobs: list[CameraJob],
        out_dir: Path,
        start_time: datetime,
        duration_s: float,
        encoder: str,
        quality: int,
        overlay: dict,
    ):
        self.jobs = jobs
        self.out_dir = Path(out_dir)
        self.stamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
        self.total_frames = int(round(duration_s * OUTPUT_FPS))
        self.encoder = encoder
        self.quality = quality
        self.overlay = overlay
        self.frames_done = 0
        self.repeats = {j.label: 0 for j in jobs}
        self.repeat_idx: dict[str, list[int]] = {j.label: [] for j in jobs}
        self.max_lag_s = 0.0
        self.fps_measured: float | None = None
        self.stopped_early = False
        self.error = ""  # set if the clock itself failed
        self._stop_event = threading.Event()
        self._writers: list[_VideoWriter] = []
        self._thread: threading.Thread | None = None
        self.running = False

    # ----------------------------------------------------------------- api
    def file_base(self, job: CameraJob) -> Path:
        """<date>_<time>_<arena>_<camera label>, per the metadata standard."""
        return self.out_dir / f"{self.stamp}_{arena_slug(job.arena)}_{camera_label(job.label, job.arena)}"

    def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        try:
            for job in self.jobs:
                self._writers.append(
                    _VideoWriter(self.file_base(job), self.encoder, self.quality, self.overlay))
        except Exception:
            for w in self._writers:  # don't leave encoders running for the other cameras
                w.abort()
            self._writers.clear()
            raise
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="rec-clock")
        self._thread.start()

    def request_stop(self) -> None:
        self._stop_event.set()

    @property
    def elapsed_s(self) -> float:
        return self.frames_done / OUTPUT_FPS

    def wait_clock(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def finalize(self) -> list[CameraResult]:
        """Close encoders and convert to standard MP4, all cameras at once.
        Blocking (seconds)."""
        self.wait_clock()
        with ThreadPoolExecutor(max_workers=max(1, len(self.jobs))) as pool:
            return list(pool.map(self._finish_camera, self.jobs, self._writers))

    def _finish_camera(self, job: CameraJob, w: _VideoWriter) -> CameraResult:
        w.finish()
        res = CameraResult(job.label, job.arena, job.slot_id,
                           timestamps=w.ts_path, frames=self.frames_done,
                           repeated=self.repeats[job.label],
                           repeated_frames=self.repeat_idx[job.label],
                           fps_measured=self.fps_measured, error=w.error or self.error)
        if w.partial.exists() and ffmpeg_util.remux_to_mp4(w.partial, w.final):
            w.partial.unlink(missing_ok=True)
            res.video = w.final
            cap = cv2.VideoCapture(str(w.final))
            if cap.isOpened():
                res.verified_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
        elif w.partial.exists():
            res.video = w.partial
            res.error = res.error or "Could not convert to standard MP4; crash-safe file kept"
        else:
            res.error = res.error or "No video file was produced"
        return res

    # ------------------------------------------------------------ internal
    def _run(self) -> None:
        try:
            self._clock()
        except Exception as e:  # noqa: BLE001 - never leave the app stuck "recording"
            self.error = f"Recording stopped by an internal error: {e!r}"
            raise
        finally:
            self.stopped_early = self.frames_done < self.total_frames
            self.running = False

    def _clock(self) -> None:
        period = 1.0 / OUTPUT_FPS
        last_seq = {j.label: -1 for j in self.jobs}
        t0 = time.perf_counter() + 0.05
        first_tick = last_tick = t0
        k = 0
        while k < self.total_frames and not self._stop_event.is_set():
            target = t0 + k * period
            _sleep_until(target)
            tick = time.perf_counter()
            if k == 0:
                first_tick = tick
            last_tick = tick
            self.max_lag_s = max(self.max_lag_s, tick - target)
            for job, w in zip(self.jobs, self._writers):
                frame, seq, cam_t = job.worker.latest()
                # No new frame since the last tick (or none at all yet): the same
                # frame is written again, so the video stays in real time.
                repeated = seq == last_seq[job.label] or frame is None
                if repeated:
                    self.repeats[job.label] += 1
                    if len(self.repeat_idx[job.label]) < 10000:
                        self.repeat_idx[job.label].append(k)
                last_seq[job.label] = seq
                w.put((frame, k, repeated, tick - t0, (cam_t - t0) if seq > 0 else None, seq))
            k += 1
            self.frames_done = k
        if k > 1 and last_tick > first_tick:
            self.fps_measured = (k - 1) / (last_tick - first_tick)
