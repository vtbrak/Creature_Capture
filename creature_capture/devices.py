"""Discovery of physical cameras.

On Windows we ask FFmpeg's DirectShow input to list video devices. FFmpeg
reports each device's *friendly name* and its *device path* ("Alternative
name"). The listing order is the DirectShow enumeration order, which is the
same order OpenCV's CAP_DSHOW backend uses for its integer indices.

The device path contains the USB instance ID. For cameras without a serial
number (typical of ELP), Windows derives that ID from the USB port the camera
is plugged into, so it is stable as long as each camera stays in the same
port - which lets us remember "this physical camera is Arena 1 Overhead"
even when Windows renumbers cameras after a reboot.

On macOS / Linux (development only) we simply probe OpenCV indices.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from creature_capture import ffmpeg_util


@dataclass
class DeviceInfo:
    id: str  # stable identifier saved in settings
    name: str  # human readable
    index: int  # backend index used to open it right now
    kind: str = "usb"  # usb | sim

    def describe(self) -> str:
        if self.kind == "sim":
            return self.name
        short = self.id
        m = re.search(r"vid_([0-9a-f]{4}).*?pid_([0-9a-f]{4}).*?#([^#]+)#", self.id, re.I)
        if m:
            short = f"VID {m.group(1).upper()} PID {m.group(2).upper()} port-id {m.group(3)}"
        return f"#{self.index}: {self.name}  [{short}]"


_DSHOW_LINE = re.compile(r'\]\s+"(?P<name>.+)"\s*(?:\((?P<kind>video|audio|none)\))?\s*$')
_ALT_LINE = re.compile(r'Alternative name\s+"(?P<alt>.+)"')


def parse_dshow_listing(text: str) -> list[tuple[str, str]]:
    """Parse ``ffmpeg -list_devices true -f dshow -i dummy`` stderr output.

    Returns [(friendly_name, device_path), ...] for video devices, in order.
    Handles both the old format (section headers) and the newer format
    where each device line ends with "(video)" / "(audio)".
    """
    devices: list[tuple[str, str]] = []
    section = None  # for the old format
    pending_video: str | None = None
    for line in text.splitlines():
        if "DirectShow video devices" in line:
            section = "video"
            continue
        if "DirectShow audio devices" in line:
            section = "audio"
            continue
        alt = _ALT_LINE.search(line)
        if alt:
            if pending_video is not None:
                devices.append((pending_video, alt.group("alt")))
                pending_video = None
            continue
        m = _DSHOW_LINE.search(line)
        if m:
            if pending_video is not None:  # previous video device had no alt name
                devices.append((pending_video, pending_video))
                pending_video = None
            kind = m.group("kind") or section
            if kind == "video":
                pending_video = m.group("name")
    if pending_video is not None:
        devices.append((pending_video, pending_video))
    return devices


def _list_windows() -> list[DeviceInfo]:
    exe = ffmpeg_util.ffmpeg_exe()
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = proc.stderr + proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    out = []
    for idx, (name, path) in enumerate(parse_dshow_listing(text)):
        out.append(DeviceInfo(id=path, name=name, index=idx))
    if not out:
        out = _probe_opencv(max_index=8)
    return out


def _probe_opencv(max_index: int = 6) -> list[DeviceInfo]:
    import cv2

    from creature_capture.camera import backend_api

    out = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, backend_api())
        ok = cap.isOpened()
        cap.release()
        if ok:
            out.append(DeviceInfo(id=f"index:{i}", name=f"Camera {i}", index=i))
    return out


def list_devices(simulated: int = 0) -> list[DeviceInfo]:
    """Return the physical cameras currently connected (+ simulated ones)."""
    if sys.platform == "win32":
        devices = _list_windows()
    else:
        devices = _probe_opencv()
    for i in range(simulated):
        devices.append(DeviceInfo(id=f"sim:{i}", name=f"Test pattern {i + 1}", index=i, kind="sim"))
    return devices


def resolve(device_ref: dict | None, devices: list[DeviceInfo]) -> DeviceInfo | None:
    """Find the currently-connected device matching a saved slot assignment."""
    if not device_ref:
        return None
    for d in devices:
        if d.id == device_ref.get("id"):
            return d
    return None
