"""Per-experiment, per-camera controls dialog.

Each control has a "Manual control" box. Ticked, the value set here is sent to
the camera; unticked, the camera keeps control of it.

Exposure and white balance each have an automatic mode in the camera, so they
get one Manual control box (beside "Auto exposure" / "Auto white balance"),
then a choice of Auto on / Auto off, and the slider only when auto is off.

Saved form (unchanged, and what the info JSON reports): for every control
``{"apply": bool, "value": number}``, where ``apply`` is "Manual control".
"""

from __future__ import annotations

import copy
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from creature_capture.camera import CONTROLS, CameraWorker, default_controls, effective_controls
from creature_capture.config import Settings
from creature_capture.ui.common import CameraView

# The camera's automatic mode -> the value it takes over when it is on.
AUTO_PAIRS = {"auto_exposure": "exposure", "auto_wb": "wb_temperature"}
_AUTO_VALUES = set(AUTO_PAIRS.values())


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

        self.manual: dict[str, QCheckBox] = {}  # control key -> its Manual control box
        self.auto_choice: dict[str, QWidget] = {}  # auto key -> the Auto on / Auto off pair
        self.auto_on: dict[str, QRadioButton] = {}
        self.auto_off: dict[str, QRadioButton] = {}
        self.spins: dict[str, QSpinBox] = {}  # value key -> number box (kept equal to its slider)
        self.sliders: dict[str, QSlider] = {}
        self.names: dict[str, QLabel] = {}
        self.reads: dict[str, QLabel] = {}  # what the camera itself reports
        self._loading = False

        info = QLabel(
            f"These settings are saved for <b>{slot['name']}</b> when running "
            f"<b>{assay_name}</b> and are re-applied every time this experiment is selected.<br>"
            "Tick <i>Manual control</i> to set a value yourself with the slider. "
            "Leave it unticked and the camera keeps control of that setting."
        )
        info.setWordWrap(True)

        self.view = CameraView(slot["name"], show_toggle=False)
        self.view.gear.hide()
        self.view.set_worker(worker, "Camera not connected")
        self.view.setMinimumSize(420, 330)

        grid = QGridLayout()
        for col, title in enumerate(("Control", "Manual control", "Value", "", "Camera reports")):
            if title:
                grid.addWidget(QLabel(f"<b>{title}</b>"), 0, col)
        for r, c in enumerate(CONTROLS, start=1):
            name = self.names[c.key] = QLabel(c.label)
            name.setToolTip(c.help)
            reads = self.reads[c.key] = QLabel("")
            reads.setStyleSheet("color:#666;")
            grid.addWidget(name, r, 0)
            grid.addWidget(reads, r, 4)
            if c.key not in _AUTO_VALUES:  # exposure / white balance follow their auto row
                box = self.manual[c.key] = QCheckBox()
                box.setToolTip("Ticked: set here. Unticked: the camera keeps control.")
                box.toggled.connect(self._changed)
                grid.addWidget(box, r, 1, Qt.AlignmentFlag.AlignHCenter)
            if c.key in AUTO_PAIRS:
                on = self.auto_on[c.key] = QRadioButton("Auto on")
                off = self.auto_off[c.key] = QRadioButton("Auto off")
                on.toggled.connect(self._changed)  # fires for either choice
                pair = self.auto_choice[c.key] = QWidget()  # own parent: one of the two only
                pl = QHBoxLayout(pair)
                pl.setContentsMargins(0, 0, 0, 0)
                pl.addWidget(on)
                pl.addWidget(off)
                pl.addStretch(1)
                grid.addWidget(pair, r, 2, 1, 2)
            else:
                name.setIndent(16 if c.key in _AUTO_VALUES else 0)
                slider = self.sliders[c.key] = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(c.minimum, c.maximum)
                slider.setMinimumWidth(160)
                spin = self.spins[c.key] = QSpinBox()
                spin.setRange(c.minimum, c.maximum)
                slider.valueChanged.connect(spin.setValue)
                spin.valueChanged.connect(slider.setValue)
                spin.valueChanged.connect(self._changed)
                grid.addWidget(slider, r, 2)
                grid.addWidget(spin, r, 3)

        self.exposure_warn = QLabel("")
        self.exposure_warn.setStyleSheet("color:#b60;")
        self.exposure_warn.setWordWrap(True)

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(lambda: self._load(default_controls()))
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

        self._load(effective_controls(self.original))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    # ----------------------------------------------------------------
    def _load(self, controls: dict) -> None:
        """Show a set of saved controls, then send them to the camera."""
        self._loading = True
        for c in CONTROLS:
            entry = controls[c.key]
            if c.key in AUTO_PAIRS:
                value = controls[AUTO_PAIRS[c.key]]
                # A manual value saved without the auto mode means auto was meant to be off.
                self.manual[c.key].setChecked(bool(entry["apply"] or value["apply"]))
                auto = bool(entry["apply"] and entry["value"])
                self.auto_on[c.key].setChecked(auto)
                self.auto_off[c.key].setChecked(not auto)
            else:
                self.spins[c.key].setValue(int(round(float(entry["value"]))))
                if c.key in self.manual:
                    self.manual[c.key].setChecked(bool(entry["apply"]))
        self._loading = False
        self._changed()

    def _collect(self) -> dict:
        """The controls as saved: {"apply": Manual control, "value": ...} each."""
        out = {}
        for c in CONTROLS:
            if c.key in AUTO_PAIRS:
                manual, auto = self.manual[c.key].isChecked(), self.auto_on[c.key].isChecked()
                value_key = AUTO_PAIRS[c.key]
                out[c.key] = {"apply": manual, "value": int(auto)}
                out[value_key] = {"apply": manual and not auto,
                                  "value": self.spins[value_key].value()}
            elif c.key not in _AUTO_VALUES:
                out[c.key] = {"apply": self.manual[c.key].isChecked(),
                              "value": self.spins[c.key].value()}
        return {c.key: out[c.key] for c in CONTROLS}  # in the usual order

    def _changed(self) -> None:
        if self._loading:
            return
        self.controls = self._collect()
        for key in self.sliders:
            if key not in _AUTO_VALUES:  # sliders can be dragged only under manual control
                on = self.manual[key].isChecked()
                self.sliders[key].setEnabled(on)
                self.spins[key].setEnabled(on)
        for auto_key, value_key in AUTO_PAIRS.items():
            manual = self.manual[auto_key].isChecked()
            self.auto_choice[auto_key].setVisible(manual)
            show_slider = self.controls[value_key]["apply"]  # manual, and auto off
            for w in (self.names[value_key], self.sliders[value_key], self.spins[value_key],
                      self.reads[value_key]):
                w.setVisible(show_slider)
        if self.worker:
            self.worker.apply_controls(self.controls)
        self._update_warning()

    def _update_warning(self) -> None:
        c = self.controls
        if c["exposure"]["apply"]:  # manual control with auto exposure off
            self.exposure_warn.setText(
                "Exposure longer than 1/32 s: the camera cannot deliver 20 fps at this "
                "setting and frames will be repeated. Use -5 or lower and raise gain/lighting."
                if c["exposure"]["value"] > -5 else "")
        else:
            self.exposure_warn.setText(
                "Auto exposure is not locked off: brightness may change between recordings.")

    def _tick(self) -> None:
        self.view.refresh()
        if self.worker:
            for key, label in self.reads.items():
                v = self.worker.read_values.get(key)
                label.setText("" if v is None else f"{v:g}")

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
