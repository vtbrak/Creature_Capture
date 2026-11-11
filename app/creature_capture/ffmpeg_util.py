"""FFmpeg helpers: locating the bundled binary, picking an encoder, remuxing."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@functools.lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    env = os.environ.get("CREATURE_CAPTURE_FFMPEG")
    if env:
        return env
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("FFmpeg not found. Reinstall Creature Capture or install FFmpeg.")


@functools.lru_cache(maxsize=4)
def encoder_works(name: str) -> bool:
    """Try a tiny encode to see if an encoder is usable on this machine."""
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=gray:s=800x600:r=20:d=0.5",
        "-c:v", name, "-pix_fmt", "yuv420p", "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def choose_encoder(preference: str = "auto") -> str:
    """NVIDIA GPU encoding unless the CPU encoder was chosen or NVENC isn't usable."""
    if preference != "libx264" and encoder_works("h264_nvenc"):
        return "h264_nvenc"
    return "libx264"


def encoder_args(encoder: str, quality: int, fps: int) -> list[str]:
    """Codec arguments. Keyframe every second keeps seeking fast and limits
    what can be lost if recording is interrupted."""
    gop = str(fps)
    if encoder == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
            "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
            "-profile:v", "high", "-g", gop, "-bf", "0",
        ]
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality),
        "-profile:v", "high", "-g", gop, "-bf", "0",
    ]


def remux_to_mp4(src: Path, dst: Path) -> bool:
    """Rewrite a crash-safe fragmented MP4 as a standard MP4 (no re-encode).

    Standard MP4 has an exact frame count in its header, which DeepLabCut and
    ezTrack (both OpenCV-based) rely on.
    """
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(dst),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


RECORDING_SUFFIX = ".recording.mp4"


def find_unfinished(base: Path) -> list[Path]:
    """Recordings left over from a crash (still in crash-safe form)."""
    if not base.exists():
        return []
    return sorted(base.rglob("*" + RECORDING_SUFFIX))


def recover(path: Path) -> Path | None:
    final = path.with_name(path.name[: -len(RECORDING_SUFFIX)] + ".mp4")
    if remux_to_mp4(path, final):
        path.unlink(missing_ok=True)
        return final
    return None
