"""Dialog to create or edit an experiment (assay) definition."""

from __future__ import annotations

import copy
import re

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from creature_capture.config import STANDARD_ASSAYS, Settings, standard_assay
from creature_capture.recorder import camera_label
from creature_capture.records import safe_name


class AssayEditor(QDialog):
    def __init__(self, settings: Settings, assay: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit experiment" if assay else "New experiment")
        self.settings = settings
        self.original_name = assay["name"] if assay else None
        a = copy.deepcopy(assay) if assay else {
            "name": "", "folder": "", "durations": [5, 10, 15, 20, 30],
            "default_duration": 10,
            "arenas": [{"name": "Arena", "cameras": [{"slot": settings.slots[0]["id"]
                                                     if settings.slots else "", "label": "Overhead"}]}],
        }
        self.name = QLineEdit(a["name"])
        self.std_assay = QComboBox()
        self.std_assay.addItem("Other (not in the Track Tamer list)", "")
        for std in STANDARD_ASSAYS:
            self.std_assay.addItem(std, std)
        self.std_assay.setCurrentIndex(max(0, self.std_assay.findData(standard_assay(a))))
        self.std_assay.setToolTip(
            "Written as \"assay\" in the info file so Track Tamer sets the test type. "
            "For \"Other\", the experiment name is written and Track Tamer asks.")
        self.folder = QLineEdit(a["folder"])
        self.folder.setPlaceholderText("e.g. NovelObject (folder inside the base folder)")
        self.durations = QLineEdit(", ".join(f"{d:g}" for d in a["durations"]))
        self.default = QDoubleSpinBox()
        self.default.setRange(0.1, 1440)
        self.default.setValue(float(a["default_duration"]))

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Assay type", self.std_assay)
        form.addRow("Output folder", self.folder)
        form.addRow("Length choices (min)", self.durations)
        form.addRow("Default length (min)", self.default)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Arena / animal", "Camera", "Camera label"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for arena in a["arenas"]:
            for cam in arena["cameras"]:
                self._add_row(arena["name"], cam["slot"], camera_label(cam["label"], arena["name"]))

        add = QPushButton("Add camera")
        add.clicked.connect(lambda: self._add_row("Arena", settings.slots[0]["id"]
                                                  if settings.slots else "", ""))
        rem = QPushButton("Remove selected")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row_btns = QHBoxLayout()
        row_btns.addWidget(add)
        row_btns.addWidget(rem)
        row_btns.addStretch(1)

        help_ = QLabel(
            "Each row is one camera recorded in this experiment. Rows with the same "
            "<i>Arena / animal</i> share one animal's information; different arena names get "
            "separate animal forms and can be switched on/off before recording. The "
            "<i>Camera label</i> names the camera in the video file name, after the arena "
            "(e.g. 2026-11-05_14-32-07_Arena1_<b>Overhead</b>.mp4). Arena names and camera "
            "labels may use only letters, digits and - (no spaces or _).")
        help_.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(help_)
        lay.addWidget(self.table)
        lay.addLayout(row_btns)
        lay.addWidget(buttons)
        self.resize(640, 460)
        self.result_assay: dict | None = None

    def _add_row(self, arena: str, slot_id: str, label: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(arena))
        combo = QComboBox()
        for s in self.settings.slots:
            combo.addItem(s["name"], s["id"])
        i = combo.findData(slot_id)
        combo.setCurrentIndex(max(0, i))
        self.table.setCellWidget(r, 1, combo)
        self.table.setItem(r, 2, QTableWidgetItem(label))

    def accept(self) -> None:
        errors = []
        name = self.name.text().strip()
        folder = safe_name(self.folder.text().strip() or name.replace(" ", ""))
        if not name:
            errors.append("Name is required.")
        for a in self.settings.assays:
            if a["name"] == name and name != self.original_name:
                errors.append(f"An experiment called '{name}' already exists.")
        try:
            durations = sorted({float(x) for x in self.durations.text().replace(";", ",").split(",")
                                if x.strip()})
        except ValueError:
            durations = []
            errors.append("Length choices must be numbers separated by commas.")
        arenas: dict[str, list] = {}
        labels = set()
        for r in range(self.table.rowCount()):
            arena = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            if arena and not re.fullmatch(r"[A-Za-z0-9-]+", arena):
                errors.append(f"Row {r + 1}: arena name '{arena}' may use only letters, "
                              "digits and - (no spaces or _).")
                continue
            slot = self.table.cellWidget(r, 1).currentData()
            cam = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
            if not arena or not cam or not slot:
                errors.append(f"Row {r + 1}: arena, camera and camera label are all required.")
                continue
            if not re.fullmatch(r"[A-Za-z0-9-]+", cam):
                errors.append(f"Row {r + 1}: camera label '{cam}' may use only letters, "
                              "digits and - (no spaces or _).")
                continue
            if (arena, cam) in labels:
                errors.append(f"{arena}: camera label '{cam}' is used twice.")
            labels.add((arena, cam))
            arenas.setdefault(arena, []).append({"slot": slot, "cam": cam})
        if not arenas:
            errors.append("Add at least one camera.")
        slots_used = [c["slot"] for cams in arenas.values() for c in cams]
        if len(slots_used) != len(set(slots_used)):
            errors.append("The same camera is used twice in this experiment.")
        if errors:
            QMessageBox.warning(self, "Please fix", "\n".join(errors))
            return
        # Stored labels must be unique across the whole experiment (they key the
        # feeds); prefix the arena only where two arenas share a camera label.
        counts: dict[str, int] = {}
        for cams in arenas.values():
            for c in cams:
                counts[c["cam"]] = counts.get(c["cam"], 0) + 1
        for arena, cams in arenas.items():
            for c in cams:
                c["label"] = f"{arena}_{c['cam']}" if counts[c["cam"]] > 1 else c["cam"]
                del c["cam"]
        self.result_assay = {
            "name": name, "standard_assay": self.std_assay.currentData(),
            "folder": folder, "durations": durations,
            "default_duration": self.default.value(),
            "arenas": [{"name": k, "cameras": v} for k, v in arenas.items()],
        }
        super().accept()
