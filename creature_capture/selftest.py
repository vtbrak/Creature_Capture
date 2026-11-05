"""Headless end-to-end check: ``CreatureCapture.exe --self-test``.

Records 3 seconds from two simulated cameras through the real recording
pipeline and verifies the output. Used by the GitHub build to make sure the
packaged .exe works, and handy on the lab PC to confirm FFmpeg/NVENC work.
Results are printed and written to <app data>/selftest.txt.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2


def run() -> int:
    from creature_capture import __version__, devices, ffmpeg_util
    from creature_capture.camera import CameraWorker
    from creature_capture.config import app_data_dir
    from creature_capture.recorder import CameraJob, RecordingSession

    lines = [f"Creature Capture {__version__} self-test  {datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Python {sys.version.split()[0]}  OpenCV {cv2.__version__}  platform {sys.platform}"]
    ok = True
    try:
        lines.append(f"FFmpeg: {ffmpeg_util.ffmpeg_exe()}")
        nv = ffmpeg_util.encoder_works("h264_nvenc")
        lines.append(f"NVIDIA encoder (h264_nvenc) available: {nv}")
        enc = ffmpeg_util.choose_encoder("auto")
        lines.append(f"Encoder selected: {enc}")

        devs = devices.list_devices(simulated=0)
        lines.append(f"Cameras found: {len(devs)}")
        for d in devs:
            lines.append(f"  {d.describe()}")

        sims = devices.list_devices(simulated=2)[-2:]
        workers = [CameraWorker(d, 30) for d in sims]
        for w in workers:
            w.start()
        time.sleep(1.0)
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [CameraJob(f"Sim{i + 1}", "Arena1", f"sim{i}", w) for i, w in enumerate(workers)]
            s = RecordingSession(jobs, Path(tmp), datetime.now(), 3.0, enc, 20,
                                 {"enabled": True, "font_scale": 0.5})
            s.start()
            s.wait_clock()
            results = s.finalize()
            for r in results:
                good = (r.video is not None and r.video.suffix == ".mp4"
                        and not r.video.name.endswith(ffmpeg_util.RECORDING_SUFFIX)
                        and r.verified_frames == 60 and not r.error)
                cap = cv2.VideoCapture(str(r.video)) if r.video else None
                fps = cap.get(cv2.CAP_PROP_FPS) if cap else 0
                size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) \
                    if cap else (0, 0)
                if cap:
                    cap.release()
                good = good and abs(fps - 20) < 0.01 and size == (800, 600)
                ok = ok and good
                lines.append(f"Test recording {r.label}: frames={r.verified_frames} fps={fps:g} "
                             f"size={size[0]}x{size[1]} repeated={r.repeated} "
                             f"{'OK' if good else 'FAIL ' + r.error}")
            lines.append(f"Clock max lag: {s.max_lag_s * 1000:.1f} ms")
        for w in workers:
            w.stop()
    except Exception as e:  # noqa: BLE001
        import traceback

        ok = False
        lines.append("EXCEPTION: " + "".join(traceback.format_exception(e)))
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    text = "\n".join(lines)
    print(text)
    try:
        (app_data_dir() / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1
