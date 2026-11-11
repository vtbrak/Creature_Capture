"""Camera capture threads and camera controls.

Each open camera runs in its own thread that continuously reads frames,
converts them to 800x600 greyscale and keeps only the newest one. The
recorder samples these "latest frames" on a shared 20 fps clock, which is
what keeps all cameras time-synchronised.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from creature_capture.config import OUTPUT_FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH
from creature_capture.devices import DeviceInfo

IS_WINDOWS = sys.platform == "win32"


def backend_api() -> int:
    if IS_WINDOWS:
        return cv2.CAP_DSHOW  # DirectShow: best support for UVC camera controls
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


# --------------------------------------------------------------------------
# Camera controls
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ControlDef:
    key: str
    label: str
    prop: int
    kind: str  # "bool" | "int"
    minimum: int = 0
    maximum: int = 1
    default: float = 0
    default_apply: bool = False
    help: str = ""


# Ranges are typical for ELP/UVC cameras under DirectShow. Values outside a
# camera's real range are clamped by the driver.
CONTROLS: list[ControlDef] = [
    ControlDef("auto_exposure", "Auto exposure", cv2.CAP_PROP_AUTO_EXPOSURE, "bool",
               default=0, default_apply=True,
               help="Keep OFF so brightness does not drift between recordings."),
    ControlDef("exposure", "Exposure", cv2.CAP_PROP_EXPOSURE, "int", -13, -1, -5, True,
               help="DirectShow units: 2^value seconds (-5 = 1/32 s, -6 = 1/64 s). "
                    "Must be -5 or lower (shorter) to sustain 20 fps."),
    ControlDef("gain", "Gain", cv2.CAP_PROP_GAIN, "int", 0, 100, 0),
    ControlDef("brightness", "Brightness", cv2.CAP_PROP_BRIGHTNESS, "int", -64, 64, 0),
    ControlDef("contrast", "Contrast", cv2.CAP_PROP_CONTRAST, "int", 0, 100, 32),
    ControlDef("gamma", "Gamma", cv2.CAP_PROP_GAMMA, "int", 72, 500, 100),
    ControlDef("sharpness", "Sharpness", cv2.CAP_PROP_SHARPNESS, "int", 0, 100, 3),
    ControlDef("auto_wb", "Auto white balance", cv2.CAP_PROP_AUTO_WB, "bool", default=0),
    ControlDef("wb_temperature", "White balance (K)", cv2.CAP_PROP_WB_TEMPERATURE, "int",
               2800, 6500, 4600),
]


def default_controls() -> dict:
    return {c.key: {"apply": c.default_apply, "value": c.default} for c in CONTROLS}


def effective_controls(saved: dict | None) -> dict:
    out = default_controls()
    for k, v in (saved or {}).items():
        if k in out and isinstance(v, dict):
            out[k].update(v)
    return out


def _bool_to_backend(key: str, on: bool) -> float:
    if key == "auto_exposure":
        if IS_WINDOWS:
            return 1.0 if on else 0.0  # OpenCV DShow: 1 = auto, 0 = manual
        return 3.0 if on else 1.0  # V4L2: 3 = aperture priority (auto), 1 = manual
    return 1.0 if on else 0.0


# --------------------------------------------------------------------------
# Frame rate check
# --------------------------------------------------------------------------
def rate_problem(measured: float, asked: float) -> str:
    """How a camera's measured frame rate compares with what is needed.

    "too_slow": below the video's own rate, so every recording will have
                repeated frames (a camera really running at 10 fps, say);
    "slow":     fast enough for the video, but clearly below the capture rate
                asked for;
    "":         fine. A small shortfall (29.97 for 30) is not a problem.
    """
    if measured < OUTPUT_FPS - 0.5:
        return "too_slow"
    if measured < asked * 0.93:
        return "slow"
    return ""


# --------------------------------------------------------------------------
# Capture thread
# --------------------------------------------------------------------------
class CameraWorker(threading.Thread):
    """Continuously reads one camera and keeps the newest greyscale frame."""

    def __init__(self, device: DeviceInfo, capture_fps: int, controls: dict | None = None):
        super().__init__(daemon=True, name=f"cam-{device.index}")
        self.device = device
        self.capture_fps = capture_fps
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._t = 0.0
        self._stop_event = threading.Event()
        self._pending: list[tuple[str, object]] = []
        if controls is not None:
            self._pending.append(("controls", controls))
        self.status = "opening"
        self.error = ""
        self.native_size = (0, 0)
        self.measured_fps = 0.0  # over the last 2 s
        self.fps_settled = False  # measured over long enough to be trusted
        self.read_values: dict[str, float] = {}
        self._fps_window: deque[float] = deque()  # frame times in the last 2 s

    # ------------------------------------------------------------- public
    def latest(self) -> tuple[np.ndarray | None, int, float]:
        with self._lock:
            return self._frame, self._seq, self._t

    def apply_controls(self, controls: dict) -> None:
        with self._lock:
            self._pending.append(("controls", controls))

    def open_driver_dialog(self) -> None:
        with self._lock:
            self._pending.append(("dialog", None))

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def healthy(self) -> bool:
        _, seq, t = self.latest()
        return seq > 0 and (time.perf_counter() - t) < 1.0

    # ----------------------------------------------------------- internal
    def _publish(self, frame: np.ndarray, t: float) -> None:
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = frame.shape[:2]
        self.native_size = (w, h)
        if (w, h) != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
            frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_AREA)
        with self._lock:
            self._frame = frame
            self._seq += 1
            self._t = t
        win = self._fps_window
        win.append(t)
        while t - win[0] > 2.0:
            win.popleft()
        span = t - win[0]
        self.measured_fps = (len(win) - 1) / span if span > 0 else 0.0
        self.fps_settled = span >= 1.5  # reads low just after opening or a gap

    def rate_flag(self) -> str:
        """rate_problem() for this camera; "" while its rate is still settling."""
        return rate_problem(self.measured_fps, self.capture_fps) if self.fps_settled else ""

    def _take_pending(self):
        with self._lock:
            items, self._pending = self._pending, []
        return items

    def run(self) -> None:
        try:
            if self.device.kind == "sim":
                self._run_sim()
            else:
                self._run_real()
        except Exception as e:  # noqa: BLE001 - show it on the feed instead of dying silently
            self.status, self.error = "error", f"Camera stopped: {e!r}"
            raise

    def _open(self):
        cap = cv2.VideoCapture(self.device.index, backend_api())
        if not cap.isOpened():
            return None
        # Order matters for DirectShow: format first, then size, then rate.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, OUTPUT_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, OUTPUT_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, self.capture_fps)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass
        return cap

    def _apply(self, cap, controls: dict) -> None:
        controls = effective_controls(controls)
        # Auto modes (the bool controls) first so manual values are not overridden.
        for c in sorted(CONTROLS, key=lambda c: c.kind != "bool"):
            entry = controls[c.key]
            if not entry.get("apply"):
                continue
            val = entry.get("value", c.default)
            if c.kind == "bool":
                val = _bool_to_backend(c.key, bool(val))
            try:
                cap.set(c.prop, float(val))
            except cv2.error:
                pass
        self._read_back(cap)

    def _read_back(self, cap) -> None:
        vals = {}
        for c in CONTROLS:
            try:
                vals[c.key] = float(cap.get(c.prop))
            except cv2.error:
                pass
        self.read_values = vals

    def _run_real(self) -> None:
        cap = None
        failures = 0
        while not self._stop_event.is_set():
            if cap is None:
                self.status = "opening"
                cap = self._open()
                if cap is None:
                    self.status = "error"
                    self.error = "Could not open camera"
                    self._stop_event.wait(2.0)
                    continue
                self.status = "live"
                self.error = ""
                self._read_back(cap)
            for kind, payload in self._take_pending():
                if kind == "controls":
                    self._apply(cap, payload)  # type: ignore[arg-type]
                elif kind == "dialog":
                    try:
                        cap.set(cv2.CAP_PROP_SETTINGS, 1)
                    except cv2.error:
                        pass
            ok, frame = cap.read()
            t = time.perf_counter()
            if not ok or frame is None:
                failures += 1
                if failures > 20:
                    self.status = "error"
                    self.error = "Camera stopped sending frames - reconnecting"
                    cap.release()
                    cap = None
                    failures = 0
                    self._stop_event.wait(1.0)
                else:
                    time.sleep(0.01)
                continue
            failures = 0
            self._publish(frame, t)
        if cap is not None:
            cap.release()
        self.status = "closed"

    def _run_sim(self) -> None:
        """Synthetic moving pattern for development on machines without cameras."""
        self.status = "live"
        period = 1.0 / max(1, self.capture_fps)
        rng = np.random.default_rng(self.device.index)
        base = (rng.random((OUTPUT_HEIGHT, OUTPUT_WIDTH)) * 40 + 90).astype(np.uint8)
        cv2.rectangle(base, (100, 75), (700, 525), 200, 3)
        next_t = time.perf_counter()
        start = next_t
        brightness = 0
        while not self._stop_event.is_set():
            for kind, payload in self._take_pending():
                if kind == "controls":
                    c = effective_controls(payload)  # type: ignore[arg-type]
                    brightness = int(c["brightness"]["value"]) if c["brightness"]["apply"] else 0
            now = time.perf_counter()
            if now < next_t:
                time.sleep(next_t - now)
            next_t += period
            t = time.perf_counter()
            el = t - start
            frame = cv2.add(base, brightness) if brightness >= 0 else cv2.subtract(base, -brightness)
            cx = int(400 + 250 * math.cos(el * (0.6 + 0.1 * self.device.index)))
            cy = int(300 + 180 * math.sin(el * (0.9 + 0.1 * self.device.index)))
            cv2.circle(frame, (cx, cy), 28, 30, -1)
            cv2.putText(frame, self.device.name, (20, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2)
            self._publish(frame, t)
        self.status = "closed"
