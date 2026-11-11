"""The Settings tab."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from creature_capture import records
from creature_capture.config import (
    OUTPUT_FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH, Settings, animals_path, app_data_dir,
)
from creature_capture.recorder import draw_overlay
from creature_capture.ui.assay_editor import AssayEditor
from creature_capture.ui.camera_controls import CameraControlsDialog
from creature_capture.ui.common import CameraManager, CameraView, EncoderProbe, gray_to_pixmap


class SettingsTab(QWidget):
    settings_changed = Signal()
    lock_changed = Signal(bool)

    def __init__(self, settings: Settings, cameras: CameraManager, encoder: EncoderProbe, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.cameras = cameras
        self.encoder = encoder
        self.lockable: list[QWidget] = []
        self._loading = False

        self.lock = QCheckBox("Lock settings  (untick to make changes)")
        self.lock.setStyleSheet("QCheckBox{font-weight:bold; font-size:14px;}")
        self.lock.setChecked(bool(settings.get("locked", False)))
        self.lock.toggled.connect(self._lock_toggled)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.addWidget(self.lock)
        for build in (self._build_output, self._build_cameras, self._build_experiments,
                      self._build_recording, self._build_overlay, self._build_animals,
                      self._build_backup, self._build_testing):
            lay.addWidget(build())
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.preview.refresh)

        self._fill_slots()
        self._fill_assays()
        self._update_example()
        self._update_overlay_preview()
        self._update_animal_status()
        self._apply_lock()

    # ------------------------------------------------- the settings boxes
    def _build_output(self) -> QGroupBox:
        """Where videos are saved."""
        out_box = QGroupBox("Output")
        self.base_path = QLineEdit(self.settings["base_path"])
        self.base_path.editingFinished.connect(self._save_output)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.base_path, 1)
        row.addWidget(browse)
        self.date_sub = QCheckBox(
            f"Put videos in a dated subfolder (e.g. {Path('OpenField', '2026-11-05')})")
        self.date_sub.setChecked(bool(self.settings.get("date_subfolders", True)))
        self.date_sub.toggled.connect(self._save_output)
        self.disk_warn = QSpinBox()
        self.disk_warn.setRange(1, 10000)
        self.disk_warn.setSuffix(" GB")
        self.disk_warn.setValue(int(self.settings.get("disk_warning_gb", 20)))
        self.disk_warn.valueChanged.connect(self._save_output)
        self.out_example = QLabel("")
        self.out_example.setStyleSheet("color:#555;")
        f = QFormLayout(out_box)
        f.addRow("Base folder", row)
        f.addRow("", self.date_sub)
        f.addRow("Warn when free space below", self.disk_warn)
        f.addRow("Example", self.out_example)
        self.lockable += [self.base_path, browse, self.date_sub, self.disk_warn]
        return out_box

    def _build_cameras(self) -> QGroupBox:
        """Which physical camera is at each camera position."""
        cam_box = QGroupBox("Cameras - assign each physical camera to a camera position and set its controls")
        self.slot_table = QTableWidget(0, 3)
        self.slot_table.setHorizontalHeaderLabels(
            ["Camera position", "Physical camera", "Camera settings"])
        header = self.slot_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.verticalHeader().hide()
        self.slot_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.slot_table.itemSelectionChanged.connect(self._preview_selected)
        self.slot_table.itemChanged.connect(self._slot_renamed)
        refresh = QPushButton("Refresh camera list")
        refresh.clicked.connect(self._refresh_devices)
        add_slot = QPushButton("Add position")
        add_slot.clicked.connect(self._add_slot)
        rem_slot = QPushButton("Remove position")
        rem_slot.clicked.connect(self._remove_slot)
        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addWidget(add_slot)
        btns.addWidget(rem_slot)
        btns.addStretch(1)
        self.preview = CameraView("Preview - select a row", show_toggle=False)
        self.preview.gear.hide()
        self.preview.setMinimumSize(360, 300)
        cam_help = QLabel(
            "Each camera is remembered by the USB port it is plugged into, so keep every "
            "camera in the same port. Select a row to see that camera's live feed and confirm "
            "it is the right one. <i>Camera controls…</i> in the same row sets its exposure, "
            "gain etc. These are kept separately for each experiment, so a camera used by more "
            "than one experiment asks which. (The same window opens from the button above each "
            "feed on the Record tab.)")
        cam_help.setWordWrap(True)
        left = QVBoxLayout()
        left.addWidget(cam_help)
        left.addWidget(self.slot_table, 1)
        left.addLayout(btns)
        cam_lay = QHBoxLayout(cam_box)
        cam_lay.addLayout(left, 3)
        cam_lay.addWidget(self.preview, 2)
        self.lockable += [self.slot_table, add_slot, rem_slot]
        return cam_box

    def _build_experiments(self) -> QGroupBox:
        """The list of experiments."""
        exp_box = QGroupBox("Experiments (shown in the Record tab's Experiment list)")
        self.assay_list = QListWidget()
        self.assay_list.itemDoubleClicked.connect(lambda _: self._edit_assay())
        new_a = QPushButton("New…")
        new_a.clicked.connect(lambda: self._edit_assay(new=True))
        edit_a = QPushButton("Edit…")
        edit_a.clicked.connect(lambda: self._edit_assay())
        del_a = QPushButton("Delete")
        del_a.clicked.connect(self._delete_assay)
        up_a = QPushButton("Move up")
        up_a.clicked.connect(lambda: self._move_assay(-1))
        down_a = QPushButton("Move down")
        down_a.clicked.connect(lambda: self._move_assay(1))
        eb = QVBoxLayout()
        for b in (new_a, edit_a, del_a, up_a, down_a):
            eb.addWidget(b)
        eb.addStretch(1)
        el = QHBoxLayout(exp_box)
        el.addWidget(self.assay_list, 1)
        el.addLayout(eb)
        self.lockable += [new_a, edit_a, del_a, up_a, down_a]
        return exp_box

    def _build_recording(self) -> QGroupBox:
        """Encoder, quality and capture rate."""
        rec_box = QGroupBox("Recording")
        self.enc_combo = QComboBox()
        self.enc_combo.addItem("Automatic (NVIDIA GPU if available)", "auto")
        self.enc_combo.addItem("NVIDIA GPU (h264_nvenc)", "h264_nvenc")
        self.enc_combo.addItem("CPU (libx264)", "libx264")
        self.enc_combo.setCurrentIndex(max(0, self.enc_combo.findData(self.settings.get("encoder", "auto"))))
        self.enc_combo.currentIndexChanged.connect(self._save_recording)
        self.enc_status = QLabel("Detecting encoder…")
        self.encoder.done.connect(lambda e: self.enc_status.setText(f"In use: {e}"))
        self.quality = QSpinBox()
        self.quality.setRange(10, 35)
        self.quality.setValue(int(self.settings.get("quality", 20)))
        self.quality.setToolTip("Lower = better quality and bigger files. 18-23 is typical.")
        self.quality.valueChanged.connect(self._save_recording)
        self.cap_fps = QComboBox()
        for v in (20, 25, 30):
            self.cap_fps.addItem(f"{v} fps", v)
        self.cap_fps.setCurrentIndex(max(0, self.cap_fps.findData(int(self.settings.get("camera_capture_fps", 30)))))
        self.cap_fps.currentIndexChanged.connect(self._save_recording)
        rf = QFormLayout(rec_box)
        rf.addRow("Video format", QLabel(f"MP4 (H.264), greyscale, {OUTPUT_WIDTH} x {OUTPUT_HEIGHT}, "
                                         f"exactly {OUTPUT_FPS} fps"))
        rf.addRow("Encoder", self.enc_combo)
        rf.addRow("", self.enc_status)
        rf.addRow("Quality (lower = better)", self.quality)
        rf.addRow("Camera capture rate", self.cap_fps)
        rf.addRow("", QLabel("<small>Capturing at 30 fps (recommended) guarantees a fresh frame for "
                             "every 20 fps video frame. Videos are always saved at 20 fps.</small>"))
        self.lockable += [self.enc_combo, self.quality, self.cap_fps]
        return rec_box

    def _build_overlay(self) -> QGroupBox:
        """The text burned into each video."""
        ov_box = QGroupBox("Text burned into the video (upper-left corner)")
        ov = self.settings["overlay"]
        self.ov_enabled = QCheckBox("Show text")
        self.ov_elapsed = QCheckBox("Elapsed time")
        self.ov_frame = QCheckBox("Frame number")
        self.ov_fps = QCheckBox("Frame rate")
        self.ov_mark = QCheckBox("Mark repeated frames with *")
        for cb, key in ((self.ov_enabled, "enabled"), (self.ov_elapsed, "show_elapsed"),
                        (self.ov_frame, "show_frame"), (self.ov_fps, "show_fps"),
                        (self.ov_mark, "mark_repeats")):
            cb.setChecked(bool(ov.get(key, True)))
            cb.toggled.connect(self._save_overlay)
        self.ov_scale = QDoubleSpinBox()
        self.ov_scale.setRange(0.3, 2.0)
        self.ov_scale.setSingleStep(0.05)
        self.ov_scale.setValue(float(ov.get("font_scale", 0.5)))
        self.ov_scale.valueChanged.connect(self._save_overlay)
        self.ov_preview = QLabel()
        self.ov_preview.setFixedSize(OUTPUT_WIDTH // 2, OUTPUT_HEIGHT // 2)
        og = QGridLayout(ov_box)
        og.addWidget(self.ov_enabled, 0, 0)
        og.addWidget(self.ov_elapsed, 1, 0)
        og.addWidget(self.ov_frame, 2, 0)
        og.addWidget(self.ov_fps, 3, 0)
        og.addWidget(self.ov_mark, 4, 0)
        sc = QHBoxLayout()
        sc.addWidget(QLabel("Text size"))
        sc.addWidget(self.ov_scale)
        sc.addStretch(1)
        og.addLayout(sc, 5, 0)
        og.addWidget(self.ov_preview, 0, 1, 7, 1)
        og.setRowStretch(6, 1)
        self.lockable += [self.ov_enabled, self.ov_elapsed, self.ov_frame, self.ov_fps,
                          self.ov_mark, self.ov_scale]
        return ov_box

    def _build_animals(self) -> QGroupBox:
        """The optional animal list."""
        an_box = QGroupBox("Animal list (optional)")
        self.animal_status = QLabel("")
        imp = QPushButton("Import CSV…")
        imp.clicked.connect(self._import_animals)
        tmpl = QPushButton("Save blank template…")
        tmpl.clicked.connect(self._save_template)
        clr = QPushButton("Clear list")
        clr.clicked.connect(self._clear_animals)
        al = QVBoxLayout(an_box)
        al.addWidget(QLabel("Import a CSV with columns such as <i>animal_id, sex, strain, dob, "
                            "treatment</i>. Animals then appear in a pick list on the Record tab "
                            "and fill in the form automatically."))
        al.addWidget(self.animal_status)
        ab = QHBoxLayout()
        ab.addWidget(imp)
        ab.addWidget(tmpl)
        ab.addWidget(clr)
        ab.addStretch(1)
        al.addLayout(ab)
        self.lockable += [imp, clr]
        return an_box

    def _build_backup(self) -> QGroupBox:
        """Export / import of all settings."""
        bk_box = QGroupBox("Backup")
        exp_s = QPushButton("Export settings…")
        exp_s.clicked.connect(self._export_settings)
        imp_s = QPushButton("Import settings…")
        imp_s.clicked.connect(self._import_settings)
        bl = QVBoxLayout(bk_box)
        bl.addWidget(QLabel(f"Settings are stored in <code>{app_data_dir()}</code> and are kept "
                            "when you install a new version."))
        bb = QHBoxLayout()
        bb.addWidget(exp_s)
        bb.addWidget(imp_s)
        bb.addStretch(1)
        bl.addLayout(bb)
        self.lockable += [imp_s]
        return bk_box

    def _build_testing(self) -> QGroupBox:
        """Test-pattern cameras."""
        dev_box = QGroupBox("Testing without cameras")
        self.sim = QSpinBox()
        self.sim.setRange(0, 8)
        self.sim.setValue(int(self.settings.get("simulated_cameras", 0)))
        self.sim.valueChanged.connect(self._save_sim)
        dl = QFormLayout(dev_box)
        dl.addRow("Test-pattern cameras", self.sim)
        dl.addRow("", QLabel("<small>Adds fake cameras that can be assigned like real ones. "
                             "Set to 0 on the recording PC.</small>"))
        self.lockable += [self.sim]
        return dev_box

    # ------------------------------------------------------------- tab
    def activate(self) -> None:
        self._fill_slots()
        self.timer.start(50)
        self._preview_selected()

    def deactivate(self) -> None:
        self.timer.stop()
        self.preview.set_worker(None, "")

    def set_recording(self, on: bool) -> None:
        """Settings cannot be changed while recording."""
        self.setEnabled(not on)

    # ------------------------------------------------------------ lock
    def _lock_toggled(self, on: bool) -> None:
        self.settings["locked"] = on
        self.settings.save()
        self._apply_lock()
        self.lock_changed.emit(on)

    def _apply_lock(self) -> None:
        locked = self.lock.isChecked()
        for w in self.lockable:
            w.setEnabled(not locked)

    def _changed(self) -> None:
        self.settings.save()
        self.settings_changed.emit()

    # ---------------------------------------------------------- output
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose base folder", self.base_path.text())
        if d:
            self.base_path.setText(str(Path(d)))
            self._save_output()

    def _save_output(self) -> None:
        self.settings["base_path"] = self.base_path.text().strip()
        self.settings["date_subfolders"] = self.date_sub.isChecked()
        self.settings["disk_warning_gb"] = self.disk_warn.value()
        self._update_example()
        self._changed()

    def _update_example(self) -> None:
        parts = ["OpenField", "2026-11-05", "2026-11-05_14-32-07_Arena1_Overhead.mp4"]
        if not self.date_sub.isChecked():
            del parts[1]
        self.out_example.setText(str(Path(self.base_path.text().strip(), *parts)))

    # --------------------------------------------------------- cameras
    def _refresh_devices(self) -> None:
        self.cameras.refresh_devices()
        self._fill_slots()
        self.settings_changed.emit()

    def _fill_slots(self) -> None:
        self._loading = True
        sel = self.slot_table.currentRow()
        self.slot_table.setRowCount(0)
        for r, slot in enumerate(self.settings.slots):
            self.slot_table.insertRow(r)
            item = QTableWidgetItem(slot["name"])
            item.setData(Qt.ItemDataRole.UserRole, slot["id"])
            self.slot_table.setItem(r, 0, item)
            combo = QComboBox()
            combo.addItem("— not assigned —", None)
            assigned = (slot.get("device") or {}).get("id")
            found = False
            for d in self.cameras.devices:
                combo.addItem(d.describe(), {"id": d.id, "name": d.name})
                if d.id == assigned:
                    combo.setCurrentIndex(combo.count() - 1)
                    found = True
            if assigned and not found:
                combo.addItem(f"(not connected) {slot['device'].get('name', assigned)}", slot["device"])
                combo.setCurrentIndex(combo.count() - 1)
            combo.currentIndexChanged.connect(lambda _=None, sid=slot["id"], c=combo: self._assign(sid, c))
            self.slot_table.setCellWidget(r, 1, combo)
            controls = QPushButton("Camera controls…")
            controls.clicked.connect(
                lambda _=None, sid=slot["id"], b=controls: self._open_camera_controls(sid, b))
            self.slot_table.setCellWidget(r, 2, controls)
        if 0 <= sel < self.slot_table.rowCount():
            self.slot_table.selectRow(sel)
        self._loading = False

    def _assign(self, slot_id: str, combo: QComboBox) -> None:
        dev = combo.currentData()
        for s in self.settings.slots:
            if s["id"] == slot_id:
                s["device"] = dev
        if dev:
            others = [s["name"] for s in self.settings.slots
                      if s["id"] != slot_id and (s.get("device") or {}).get("id") == dev["id"]]
            if others:
                QMessageBox.warning(self, "Camera already assigned",
                                    f"This physical camera is also assigned to: {', '.join(others)}.\n"
                                    "Each position should normally have its own camera.")
        self._changed()
        self.slot_table.selectRow(next(i for i, s in enumerate(self.settings.slots) if s["id"] == slot_id))
        self._preview_selected()

    def _experiments_for(self, slot_id: str) -> tuple[list[str], bool]:
        """The experiments a camera position's controls can be set for: the ones
        that use it, or every experiment if none does yet (a new position).
        Also returns whether any experiment uses it."""
        using = [a["name"] for a in self.settings.assays
                 if any(c["slot"] == slot_id for ar in a["arenas"] for c in ar["cameras"])]
        return (using or [a["name"] for a in self.settings.assays]), bool(using)

    def _choose_experiment(self, slot_id: str, button: QPushButton) -> str | None:
        """Camera controls are kept per experiment: ask which, if there is a choice."""
        names, in_use = self._experiments_for(slot_id)
        if len(names) == 1:
            return names[0]
        menu = QMenu(self)
        menu.addAction("Camera controls for which experiment?" if in_use else
                       "Not used by an experiment yet. Set its controls for:").setEnabled(False)
        for name in names:
            menu.addAction(name)
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        return chosen.text() if chosen else None

    def _open_camera_controls(self, slot_id: str, button: QPushButton) -> None:
        row = next(i for i, s in enumerate(self.settings.slots) if s["id"] == slot_id)
        self.slot_table.selectRow(row)  # the preview shows the camera being adjusted
        assay_name = self._choose_experiment(slot_id, button)
        if assay_name:
            worker = self.cameras.worker_for_slot(slot_id)  # None if not assigned / connected
            CameraControlsDialog(self.settings, assay_name, slot_id, worker, self).exec()

    def _preview_selected(self) -> None:
        if self._loading:
            return
        r = self.slot_table.currentRow()
        if r < 0 or r >= len(self.settings.slots):
            self.preview.set_worker(None, "Select a camera position")
            return
        slot = self.settings.slots[r]
        self.preview.title.setText(f"<b>Preview - {slot['name']}</b>")
        w = self.cameras.worker_for_slot(slot["id"])
        self.preview.set_worker(w, "Not assigned" if not slot.get("device") else "Not connected")

    def _slot_renamed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        slot = self.settings.slot(sid)
        if slot and item.text().strip():
            slot["name"] = item.text().strip()
            self._changed()

    def _add_slot(self) -> None:
        name, ok = QInputDialog.getText(self, "Add camera position", "Name (e.g. Arena 3 Overhead):")
        if not ok or not name.strip():
            return
        sid = records.safe_name(name.strip().replace(" ", ""))
        base, n = sid, 2
        while self.settings.slot(sid):
            sid, n = f"{base}{n}", n + 1
        self.settings.slots.append({"id": sid, "name": name.strip(), "device": None})
        self._fill_slots()
        self._changed()

    def _remove_slot(self) -> None:
        r = self.slot_table.currentRow()
        if r < 0:
            return
        slot = self.settings.slots[r]
        used = [a["name"] for a in self.settings.assays
                for ar in a["arenas"] for c in ar["cameras"] if c["slot"] == slot["id"]]
        if used:
            QMessageBox.warning(self, "In use", f"'{slot['name']}' is used by: {', '.join(sorted(set(used)))}."
                                "\nRemove it from those experiments first.")
            return
        if QMessageBox.question(self, "Remove", f"Remove camera position '{slot['name']}'?") \
                == QMessageBox.StandardButton.Yes:
            del self.settings.slots[r]
            self._fill_slots()
            self._changed()

    # ----------------------------------------------------- experiments
    def _fill_assays(self) -> None:
        self.assay_list.clear()
        for a in self.settings.assays:
            n = sum(len(ar["cameras"]) for ar in a["arenas"])
            self.assay_list.addItem(f"{a['name']}   —  {n} camera(s), folder '{a['folder']}', "
                                    f"default {a['default_duration']:g} min")

    def _edit_assay(self, new: bool = False) -> None:
        r = self.assay_list.currentRow()
        if not new and r < 0:
            return
        assay = None if new else self.settings.assays[r]
        dlg = AssayEditor(self.settings, assay, self)
        if dlg.exec() and dlg.result_assay:
            if new:
                self.settings.assays.append(dlg.result_assay)
            else:
                old = self.settings.assays[r]["name"]
                self.settings.assays[r] = dlg.result_assay
                if old != dlg.result_assay["name"]:
                    cs = self.settings["camera_settings"]
                    if old in cs:
                        cs[dlg.result_assay["name"]] = cs.pop(old)
            self._fill_assays()
            self._changed()

    def _delete_assay(self) -> None:
        r = self.assay_list.currentRow()
        if r < 0:
            return
        if len(self.settings.assays) == 1:
            QMessageBox.warning(self, "Cannot delete", "At least one experiment is required.")
            return
        name = self.settings.assays[r]["name"]
        if QMessageBox.question(self, "Delete", f"Delete experiment '{name}'?\n"
                                "(Recorded videos are not affected.)") == QMessageBox.StandardButton.Yes:
            del self.settings.assays[r]
            self.settings["camera_settings"].pop(name, None)
            self._fill_assays()
            self._changed()

    def _move_assay(self, delta: int) -> None:
        r = self.assay_list.currentRow()
        n = r + delta
        if r < 0 or not 0 <= n < len(self.settings.assays):
            return
        a = self.settings.assays
        a[r], a[n] = a[n], a[r]
        self._fill_assays()
        self.assay_list.setCurrentRow(n)
        self._changed()

    # ------------------------------------------------------- recording
    def _save_recording(self) -> None:
        old_fps = self.settings.get("camera_capture_fps")
        old_enc = self.settings.get("encoder")
        self.settings["encoder"] = self.enc_combo.currentData()
        self.settings["quality"] = self.quality.value()
        self.settings["camera_capture_fps"] = self.cap_fps.currentData()
        if old_enc != self.settings["encoder"]:
            self.encoder.result = None
            self.enc_status.setText("Detecting encoder…")
            self.encoder.start()
        if old_fps != self.settings["camera_capture_fps"]:
            self.cameras.restart_all()
        self._changed()

    # --------------------------------------------------------- overlay
    def _save_overlay(self) -> None:
        self.settings["overlay"] = {
            "enabled": self.ov_enabled.isChecked(),
            "font_scale": round(self.ov_scale.value(), 2),
            "show_elapsed": self.ov_elapsed.isChecked(),
            "show_frame": self.ov_frame.isChecked(),
            "show_fps": self.ov_fps.isChecked(),
            "mark_repeats": self.ov_mark.isChecked(),
        }
        self._update_overlay_preview()
        self._changed()

    def _update_overlay_preview(self) -> None:
        frame = np.full((OUTPUT_HEIGHT, OUTPUT_WIDTH), 128, np.uint8)
        frame[::40, :] = 100
        frame[:, ::40] = 100
        ov = self.settings["overlay"]
        if ov.get("enabled", True):
            frame = draw_overlay(frame, 4149, OUTPUT_FPS, True, ov)
        self.ov_preview.setPixmap(gray_to_pixmap(frame, OUTPUT_WIDTH // 2, OUTPUT_HEIGHT // 2))
        self.ov_preview.setToolTip("Preview at half size (frame 4149, a repeated frame)")

    # ----------------------------------------------------- animal list
    def _update_animal_status(self) -> None:
        p = animals_path()
        if p.exists():
            try:
                n = len(records.load_animal_list(p))
            except (OSError, UnicodeDecodeError):
                n = 0
            self.animal_status.setText(f"{n} animal(s) loaded.")
        else:
            self.animal_status.setText("No animal list loaded.")

    def _import_animals(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import animal list", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            animals = records.load_animal_list(Path(path))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        if not animals:
            QMessageBox.warning(self, "Import failed",
                                "No animals found. The CSV needs a header row with an "
                                "'animal_id' (or 'ID') column.")
            return
        shutil.copyfile(path, animals_path())
        self._update_animal_status()
        self._changed()

    def _save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save template", "animals.csv", "CSV files (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["animal_id", "sex", "strain", "dob", "treatment"])

    def _clear_animals(self) -> None:
        animals_path().unlink(missing_ok=True)
        self._update_animal_status()
        self._changed()

    # ---------------------------------------------------------- backup
    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "creature_capture_settings.json",
                                              "JSON (*.json)")
        if path:
            self.settings.export_to(Path(path))

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.settings.import_from(Path(path))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Import failed", str(e))
            return
        QMessageBox.information(self, "Imported", "Settings imported. Restart Creature Capture "
                                "to make sure everything is refreshed.")
        self.settings_changed.emit()

    # ------------------------------------------------------------- dev
    def _save_sim(self) -> None:
        self.settings["simulated_cameras"] = self.sim.value()
        self.settings.save()
        self._refresh_devices()
