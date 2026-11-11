"""Shared application state and widgets."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
)

from creature_capture import devices as devmod
from creature_capture import ffmpeg_util
from creature_capture.camera import CameraWorker
from creature_capture.config import OUTPUT_FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH, Settings


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


def greyed_out(pm: QPixmap, text: str) -> QPixmap:
    """Wash a feed out to flat grey with a label over it (camera not being recorded)."""
    p = QPainter(pm)
    p.fillRect(pm.rect(), QColor(150, 150, 150, 215))
    font = p.font()
    font.setBold(True)
    font.setPixelSize(max(14, pm.height() // 12))
    p.setFont(font)
    p.setPen(QColor(50, 50, 50))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with "…" when there isn't room,
    instead of stopping the window from being made narrower. The full text is
    in its tooltip."""

    def __init__(self, text: str = "", bold: bool = False, parent=None):
        super().__init__(parent)
        if bold:
            font = self.font()
            font.setBold(True)
            self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 2)
        self._full = ""
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def full_width(self) -> int:
        """The width needed to show the whole text."""
        return self.fontMetrics().horizontalAdvance(self._full) + 4

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(0, self.width())))


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

    # Header labels: the long ones when they fit beside the whole title, else the short ones.
    TOGGLE_TEXT = ("Record this camera", "Record")
    GEAR_TEXT = ("Camera controls…", "Controls…")
    TITLE_MIN_WIDTH = 80  # the camera's name always keeps at least this much room

    LIVE_STYLE = "background:#111; color:#bbb;"
    OFF_STYLE = "background:#969696; color:#333; border:3px dashed #555;"
    # Border when the camera is running below the rate asked for (see camera.rate_problem).
    RATE_STYLE = {"": LIVE_STYLE,
                  "slow": LIVE_STYLE + "border:3px solid #d08000;",
                  "too_slow": LIVE_STYLE + "border:3px solid #cc0000;"}
    OFF_TEXT = "NOT RECORDING"

    def __init__(self, title: str, show_toggle: bool = True, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.worker: CameraWorker | None = None
        self.slot_id = ""  # set by the Record tab: the camera position shown
        self.arena = ""  # ... and the arena it belongs to
        self._last_seq = -1
        self._recording = False
        self._off = False  # will not be recorded: shown greyed out
        self._rate_problem = ""  # "", "slow" or "too_slow": the camera's frame rate
        self._missing_text = "No camera"

        self._title = title
        self.title = ElidedLabel(title, bold=True)  # also shows "● REC" while recording
        self.title.setMinimumWidth(self.TITLE_MIN_WIDTH)
        self.toggle = QCheckBox()
        self.toggle.setChecked(True)
        self.toggle.setVisible(show_toggle)
        self.toggle.setToolTip(self.TOGGLE_TEXT[0])
        self.toggle.toggled.connect(self.enabled_changed)
        self.gear = QToolButton()
        self.gear.setToolTip(self.GEAR_TEXT[0])
        self.gear.clicked.connect(self.controls_requested)
        # Each control may be as narrow as its short label, and _fit_header picks the
        # label that fits. So a narrow window gets short labels, not a wide minimum.
        self._long_controls_width = 32  # spacing and margins, + the long labels (below)
        for w, (long, short) in ((self.toggle, self.TOGGLE_TEXT), (self.gear, self.GEAR_TEXT)):
            w.setText(short)
            w.setMinimumWidth(w.sizeHint().width())
            w.setText(long)
            self._long_controls_width += w.sizeHint().width()
            w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._compact = False

        head = QHBoxLayout()
        head.addWidget(self.title, 1)  # takes the spare width, and gives it up first
        head.addWidget(self.toggle)
        head.addWidget(self.gear)

        self.image = QLabel("No camera")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(160, 120)  # the feed shrinks with the window down to this
        self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image.setStyleSheet(self.LIVE_STYLE)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#666;")
        # Never sets the feed's width: a long status is cut off (it is also the tooltip).
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status.setFixedHeight(self.status.fontMetrics().height() + 2)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(head)
        lay.addWidget(self.image, 1)
        lay.addWidget(self.status)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_header()

    def _fit_header(self) -> None:
        """Long labels only if the whole title still fits beside them: the camera's
        name matters more than the wording of the two controls."""
        compact = self.width() < self.title.full_width() + self._long_controls_width
        if compact != self._compact:
            self._compact = compact
            self.toggle.setText(self.TOGGLE_TEXT[compact])
            self.gear.setText(self.GEAR_TEXT[compact])

    def set_worker(self, worker: CameraWorker | None, missing_text: str = "") -> None:
        self.worker = worker
        self._last_seq = -1
        if worker is None:
            self._missing_text = missing_text or "No camera assigned"
            self._show_placeholder()
            self.status.setText("")

    def _show_placeholder(self) -> None:
        """What the picture area says when there is no camera to show."""
        self.image.setPixmap(QPixmap())
        self.image.setText(f"{self.OFF_TEXT}\n\n{self._missing_text}" if self._off
                           else self._missing_text)

    def set_recording(self, on: bool) -> None:
        self._recording = on
        self._show_title()

    def set_title(self, title: str) -> None:
        self._title = title
        self._show_title()

    def _show_title(self) -> None:
        # The REC mark is part of the title so that it never needs extra width.
        self.title.set_full_text(("● REC  " if self._recording else "") + self._title)
        self.title.setStyleSheet("color:#d00;" if self._recording else "")
        self._fit_header()

    def set_off(self, off: bool) -> None:
        """Grey the view out when this camera will not be recorded (its arena or
        its own "Record this camera" box is switched off), camera or no camera."""
        self._off = off
        self._restyle()
        self.title.setEnabled(not off)
        self._last_seq = -1  # redraw the feed in its new look on the next refresh
        if self.worker is None:
            self._show_placeholder()

    def _restyle(self) -> None:
        style = self.OFF_STYLE if self._off else self.RATE_STYLE[self._rate_problem]
        if style != self.image.styleSheet():
            self.image.setStyleSheet(style)

    def refresh(self, first_status: str = "") -> None:
        """Draw the newest frame and the status line. ``first_status`` goes at the
        start of the line, where it stays visible when the line is cut short."""
        w = self.worker
        if w is None:
            return
        frame, seq, _ = w.latest()
        if frame is not None and seq != self._last_seq:
            self._last_seq = seq
            pm = gray_to_pixmap(frame, self.image.width(), self.image.height())
            self.image.setPixmap(greyed_out(pm, self.OFF_TEXT) if self._off else pm)
        problem = ""
        if w.status == "error":
            text = f"<span style='color:#c00'>{w.error}</span>"
        elif w.status == "opening":
            text = "Opening camera…"
        elif seq > 0 and not w.healthy:
            problem = "too_slow"
            text = "<span style='color:#c00'><b>⚠ No frames from the camera</b> for over a second</span>"
        else:
            nw, nh = w.native_size
            size = f"{nw}x{nh}" if nw else "?"
            if (nw, nh) not in ((OUTPUT_WIDTH, OUTPUT_HEIGHT), (0, 0)):
                size += f" (resized to {OUTPUT_WIDTH}x{OUTPUT_HEIGHT})"
            fps, asked = w.measured_fps, w.capture_fps
            problem = w.rate_flag()
            if problem == "too_slow":
                rate = (f"<span style='color:#c00'><b>⚠ {fps:.1f} fps: too slow</b> for "
                        f"{OUTPUT_FPS} fps video, frames will be repeated</span> (asked for {asked:g})")
            elif problem == "slow":
                rate = (f"<span style='color:#b60'><b>⚠ {fps:.1f} fps</b>: below the "
                        f"{asked:g} asked for</span>")
            else:
                rate = f"Camera: {fps:4.1f} fps"
            text = f"{first_status}{rate}, {size}"
        if problem != self._rate_problem:
            self._rate_problem = problem
            self._restyle()
        if text != self.status.text():
            self.status.setText(text)
            self.status.setToolTip(text)
