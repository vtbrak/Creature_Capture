"""Shared application state and widgets."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
)

from creature_capture import devices as devmod
from creature_capture import ffmpeg_util
from creature_capture.camera import CameraWorker
from creature_capture.config import OUTPUT_HEIGHT, OUTPUT_WIDTH, Settings


class CameraManager:
    """Owns the capture threads. Cameras are opened on demand and shared, so
    the Record tab and the Settings preview can show the same camera."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.devices: list[devmod.DeviceInfo] = []
        self.workers: dict[str, CameraWorker] = {}

    def refresh_devices(self) -> list[devmod.DeviceInfo]:
        self.devices = devmod.list_devices(int(self.settings.get("simulated_cameras", 0)))
        # Restart any open camera whose backend index changed.
        by_id = {d.id: d for d in self.devices}
        for dev_id, w in list(self.workers.items()):
            d = by_id.get(dev_id)
            if d is None or d.index != w.device.index:
                w.stop()
                del self.workers[dev_id]
        return self.devices

    def device_for_slot(self, slot_id: str) -> devmod.DeviceInfo | None:
        slot = self.settings.slot(slot_id)
        if not slot:
            return None
        return devmod.resolve(slot.get("device"), self.devices)

    def worker(self, device: devmod.DeviceInfo, controls: dict | None = None) -> CameraWorker:
        w = self.workers.get(device.id)
        if w is None or not w.is_alive():
            w = CameraWorker(device, int(self.settings.get("camera_capture_fps", 30)), controls)
            w.start()
            self.workers[device.id] = w
        elif controls is not None:
            w.apply_controls(controls)
        return w

    def worker_for_slot(self, slot_id: str, controls: dict | None = None) -> CameraWorker | None:
        d = self.device_for_slot(slot_id)
        return self.worker(d, controls) if d else None

    def keep_only(self, device_ids: set[str]) -> None:
        for dev_id in list(self.workers):
            if dev_id not in device_ids:
                self.workers.pop(dev_id).stop()

    def restart_all(self) -> None:
        for w in self.workers.values():
            w.stop()
        self.workers.clear()

    def shutdown(self) -> None:
        workers = list(self.workers.values())
        self.restart_all()
        for w in workers:
            w.join(timeout=2)


class EncoderProbe(QObject):
    """Detects NVENC in the background at startup (takes ~1 s)."""

    done = Signal(str)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.result: str | None = None

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        self.result = ffmpeg_util.choose_encoder(self.settings.get("encoder", "auto"))
        self.done.emit(self.result)

    def get(self) -> str:
        if self.result is None:  # asked before the background check finished
            self._run()
        return self.result


def gray_to_pixmap(frame: np.ndarray, w: int, h: int) -> QPixmap:
    frame = np.ascontiguousarray(frame)
    img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0],
                 QImage.Format.Format_Grayscale8)
    # Scale first (a copy, so the frame's memory isn't kept), then convert only the
    # small image. Fast scaling keeps the GUI thread light so it never delays
    # capture/recording.
    return QPixmap.fromImage(img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.FastTransformation))


def free_space_gb(path: str | Path) -> float | None:
    p = Path(path)
    while not p.exists():
        if p.parent == p:
            return None
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return None


class CameraView(QFrame):
    """A live feed with title, status line, enable toggle and controls button."""

    enabled_changed = Signal(bool)
    controls_requested = Signal()

    def __init__(self, title: str, show_toggle: bool = True, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.worker: CameraWorker | None = None
        self.slot_id = ""  # set by the Record tab: the camera position shown
        self.arena = ""  # ... and the arena it belongs to
        self._last_seq = -1
        self._recording = False

        self.title = QLabel(f"<b>{title}</b>")
        self.rec = QLabel("")
        self.toggle = QCheckBox("Record this camera")
        self.toggle.setChecked(True)
        self.toggle.setVisible(show_toggle)
        self.toggle.toggled.connect(self.enabled_changed)
        self.gear = QToolButton()
        self.gear.setText("Camera controls…")
        self.gear.clicked.connect(self.controls_requested)

        head = QHBoxLayout()
        head.addWidget(self.title)
        head.addWidget(self.rec)
        head.addStretch(1)
        head.addWidget(self.toggle)
        head.addWidget(self.gear)

        self.image = QLabel("No camera")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(240, 180)
        self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image.setStyleSheet("background:#111; color:#bbb;")

        self.status = QLabel("")
        self.status.setStyleSheet("color:#666;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(head)
        lay.addWidget(self.image, 1)
        lay.addWidget(self.status)

    def set_worker(self, worker: CameraWorker | None, missing_text: str = "") -> None:
        self.worker = worker
        self._last_seq = -1
        if worker is None:
            self.image.setPixmap(QPixmap())
            self.image.setText(missing_text or "No camera assigned")
            self.status.setText("")

    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.rec.setText("<span style='color:#d00'>● REC</span>" if on else "")

    def set_off(self, off: bool) -> None:
        self.image.setStyleSheet(
            "background:#111; color:#bbb;" + ("border:3px solid #888;" if off else "")
        )

    def refresh(self, extra_status: str = "") -> None:
        w = self.worker
        if w is None:
            return
        frame, seq, _ = w.latest()
        if frame is not None and seq != self._last_seq:
            self._last_seq = seq
            self.image.setPixmap(gray_to_pixmap(frame, self.image.width(), self.image.height()))
        if w.status == "error":
            self.status.setText(f"<span style='color:#c00'>{w.error}</span>")
        elif w.status == "opening":
            self.status.setText("Opening camera…")
        else:
            nw, nh = w.native_size
            size = f"{nw}x{nh}" if nw else "?"
            warn = ("" if (nw, nh) in ((OUTPUT_WIDTH, OUTPUT_HEIGHT), (0, 0))
                    else f" (resized to {OUTPUT_WIDTH}x{OUTPUT_HEIGHT})")
            self.status.setText(f"Camera: {w.measured_fps:4.1f} fps, {size}{warn}{extra_status}")
