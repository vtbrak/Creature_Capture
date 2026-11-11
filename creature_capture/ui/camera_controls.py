"""Per-assay, per-camera controls dialog."""

from __future__ import annotations

import copy
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from creature_capture.camera import CONTROLS, CameraWorker, default_controls, effective_controls
from creature_capture.config import Settings
from creature_capture.ui.common import CameraView


class CameraControlsDialog(QDialog):
    def __init__(self, settings: Settings, assay_name: str, slot_id: str,
                 worker: CameraWorker | None, parent=None):
        super().__init__(parent)
        slot = settings.slot(slot_id) or {"name": slot_id}
        self.setWindowTitle(f"Camera controls - {slot['name']} - {assay_name}")
        self.settings = settings
        self.worker = worker
        self.cam_settings = settings.camera_settings(assay_name, slot_id)
        self.original = copy.deepcopy(self.cam_settings.get("controls", {}))
        self.controls = effective_controls(self.original)
        self.rows: dict[str, tuple] = {}

        info = QLabel(
            f"These settings are saved for <b>{slot['name']}</b> when running "
            f"<b>{assay_name}</b> and are re-applied every time this experiment is selected. "
            "Untick <i>Apply</i> to leave a control at the camera's own value."
        )
        info.setWordWrap(True)

        self.view = CameraView(slot["name"], show_toggle=False)
        self.view.gear.hide()
        self.view.set_worker(worker, "Camera not connected")
        self.view.setMinimumSize(420, 330)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Apply</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Control</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Value</b>"), 0, 2, 1, 2)
        grid.addWidget(QLabel("<b>Camera reports</b>"), 0, 4)
        for r, c in enumerate(CONTROLS, start=1):
            entry = self.controls[c.key]
            apply = QCheckBox()
            apply.setChecked(bool(entry["apply"]))
            name = QLabel(c.label)
            name.setToolTip(c.help)
            reads = QLabel("")
            reads.setStyleSheet("color:#666;")
            if c.kind == "bool":
                val = QCheckBox("On")
                val.setChecked(bool(entry["value"]))
                val.toggled.connect(lambda _=None, k=c.key: self._changed(k))
                grid.addWidget(val, r, 2, 1, 2)
                widgets = (apply, val, None)
            else:
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(c.minimum, c.maximum)
                spin = QSpinBox()
                spin.setRange(c.minimum, c.maximum)
                v = int(round(float(entry["value"])))
                slider.setValue(v)
                spin.setValue(v)
                slider.valueChanged.connect(spin.setValue)
                spin.valueChanged.connect(slider.setValue)
                spin.valueChanged.connect(lambda _=None, k=c.key: self._changed(k))
                grid.addWidget(slider, r, 2)
                grid.addWidget(spin, r, 3)
                widgets = (apply, spin, slider)
            apply.toggled.connect(lambda _=None, k=c.key: self._changed(k))
            grid.addWidget(apply, r, 0)
            grid.addWidget(name, r, 1)
            grid.addWidget(reads, r, 4)
            self.rows[c.key] = (*widgets, reads)
            self._set_row_enabled(c.key)

        self.exposure_warn = QLabel("")
        self.exposure_warn.setStyleSheet("color:#b60;")
        self.exposure_warn.setWordWrap(True)

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        driver = QPushButton("Open camera driver dialog…")
        driver.setToolTip("Windows only. Opens the camera's own settings window "
                          "(includes anti-flicker / power-line frequency).")
        driver.setEnabled(sys.platform == "win32" and worker is not None)
        driver.clicked.connect(lambda: worker and worker.open_driver_dialog())
        extra = QHBoxLayout()
        extra.addWidget(reset)
        extra.addWidget(driver)
        extra.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        right = QVBoxLayout()
        right.addWidget(info)
        right.addLayout(grid)
        right.addWidget(self.exposure_warn)
        right.addLayout(extra)
        right.addStretch(1)
        right_w = QWidget()
        right_w.setLayout(right)

        body = QHBoxLayout()
        body.addWidget(self.view, 1)
        body.addWidget(right_w)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self._update_warning()

    # ----------------------------------------------------------------
    def _collect(self) -> dict:
        out = {}
        for c in CONTROLS:
            apply, val, _slider, _reads = self.rows[c.key]
            v = val.isChecked() if c.kind == "bool" else val.value()
            out[c.key] = {"apply": apply.isChecked(), "value": int(v)}
        return out

    def _set_row_enabled(self, key: str) -> None:
        apply, val, slider, _ = self.rows[key]
        val.setEnabled(apply.isChecked())
        if slider is not None:
            slider.setEnabled(apply.isChecked())

    def _changed(self, key: str) -> None:
        self._set_row_enabled(key)
        self.controls = self._collect()
        if self.worker:
            self.worker.apply_controls(self.controls)
        self._update_warning()

    def _update_warning(self) -> None:
        c = self.controls
        manual = c["auto_exposure"]["apply"] and not c["auto_exposure"]["value"]
        if manual and c["exposure"]["apply"] and c["exposure"]["value"] > -5:
            self.exposure_warn.setText(
                "Exposure longer than 1/32 s: the camera cannot deliver 20 fps at this "
                "setting and frames will be repeated. Use -5 or lower and raise gain/lighting.")
        elif not manual:
            self.exposure_warn.setText(
                "Auto exposure is not locked off: brightness may change between recordings.")
        else:
            self.exposure_warn.setText("")

    def _reset(self) -> None:
        d = default_controls()
        for c in CONTROLS:
            apply, val, _slider, _ = self.rows[c.key]
            apply.setChecked(d[c.key]["apply"])
            if c.kind == "bool":
                val.setChecked(bool(d[c.key]["value"]))
            else:
                val.setValue(int(d[c.key]["value"]))

    def _tick(self) -> None:
        self.view.refresh()
        if self.worker:
            for c in CONTROLS:
                v = self.worker.read_values.get(c.key)
                self.rows[c.key][3].setText("" if v is None else f"{v:g}")

    def accept(self) -> None:
        self.cam_settings["controls"] = self._collect()
        self.settings.save()
        self.timer.stop()
        super().accept()

    def reject(self) -> None:
        if self.worker:
            self.worker.apply_controls(self.original)
        self.timer.stop()
        super().reject()
