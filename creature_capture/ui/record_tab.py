"""The Record tab: experiment selection, animal info, live feeds, start/stop."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from creature_capture import records
from creature_capture.camera import effective_controls
from creature_capture.config import OUTPUT_FPS, Settings, animals_path
from creature_capture.recorder import CameraJob, RecordingSession, format_elapsed
from creature_capture.ui.camera_controls import CameraControlsDialog
from creature_capture.ui.common import CameraManager, CameraView, EncoderProbe, free_space_gb

MB_PER_MIN_PER_CAMERA = 40  # generous estimate for disk-space checks


class AnimalForm(QGroupBox):
    """Animal information for one arena. Checkable when the assay has more
    than one arena, so an unused arena can be switched off before starting."""

    def __init__(self, arena_name: str, checkable: bool, animals: list[dict], parent=None):
        super().__init__(f"{arena_name} - animal", parent)
        self.arena_name = arena_name
        self.setCheckable(checkable)
        if checkable:
            self.setTitle(f"{arena_name} - record this arena")
            self.setChecked(True)
        self.fields: dict[str, QWidget] = {}
        form = QFormLayout(self)

        self.pick = QComboBox()
        self.pick.setEditable(False)
        self.pick.addItem("— pick from animal list —", None)
        for a in animals:
            label = a["animal_id"]
            extra = " / ".join(x for x in (a.get("sex"), a.get("strain"), a.get("treatment")) if x)
            self.pick.addItem(f"{label}   {extra}", a)
        self.pick.setVisible(bool(animals))
        self.pick.currentIndexChanged.connect(self._picked)
        if animals:
            form.addRow("Animal list", self.pick)

        for key, label, required in records.ANIMAL_FIELDS:
            if key == "sex":
                w = QComboBox()
                w.addItems(["", "M", "F", "Unknown"])
            elif key == "dob":
                w = QDateEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("yyyy-MM-dd")
                w.setMinimumDate(QDate(1900, 1, 1))
                w.setSpecialValueText("not set")
                w.setDate(w.minimumDate())
            elif key == "notes":
                w = QPlainTextEdit()
                w.setFixedHeight(48)
            else:
                w = QLineEdit()
            self.fields[key] = w
            form.addRow(f"{label}{' *' if required else ''}", w)

    def _picked(self) -> None:
        a = self.pick.currentData()
        if not a:
            return
        self.set_values(a)

    def set_values(self, a: dict) -> None:
        for key, w in self.fields.items():
            if key not in a:
                continue
            v = a[key]
            if isinstance(w, QLineEdit):
                w.setText(v)
            elif isinstance(w, QComboBox):
                i = w.findText(v, Qt.MatchFlag.MatchFixedString)
                if i < 0 and v:
                    w.addItem(v)
                    i = w.count() - 1
                w.setCurrentIndex(max(0, i))
            elif isinstance(w, QDateEdit):
                d = QDate.fromString(v, "yyyy-MM-dd")
                if not d.isValid():
                    for fmt in ("M/d/yyyy", "MM/dd/yyyy", "d/M/yyyy", "yyyy/MM/dd", "M/d/yy"):
                        d = QDate.fromString(v, fmt)
                        if d.isValid():
                            break
                w.setDate(d if d.isValid() else w.minimumDate())

    def values(self) -> dict:
        out = {}
        for key, w in self.fields.items():
            if isinstance(w, QLineEdit):
                out[key] = w.text().strip()
            elif isinstance(w, QComboBox):
                out[key] = w.currentText().strip()
            elif isinstance(w, QDateEdit):
                out[key] = "" if w.date() == w.minimumDate() else w.date().toString("yyyy-MM-dd")
            elif isinstance(w, QPlainTextEdit):
                out[key] = w.toPlainText().strip()
        return out

    def clear_for_next_animal(self) -> None:
        self.fields["animal_id"].clear()
        self.fields["notes"].clear()
        self.pick.setCurrentIndex(0)

    @property
    def active(self) -> bool:
        return not self.isCheckable() or self.isChecked()


class _Finisher(QObject):
    finished = Signal(object)


class RecordTab(QWidget):
    recording_changed = Signal(bool)

    def __init__(self, settings: Settings, cameras: CameraManager, encoder: EncoderProbe, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.cameras = cameras
        self.encoder = encoder
        self.session: RecordingSession | None = None
        self.session_meta: dict = {}
        self.finalizing = False
        self.views: dict[str, CameraView] = {}  # camera label -> view
        self.view_slot: dict[str, str] = {}  # camera label -> slot id
        self.view_arena: dict[str, str] = {}
        self.forms: dict[str, AnimalForm] = {}
        self.animals: list[dict] = []
        self._finisher = _Finisher()
        self._finisher.finished.connect(self._on_finalized)

        # ---- top bar
        self.assay_combo = QComboBox()
        self.assay_combo.setMinimumWidth(180)
        self.assay_combo.currentTextChanged.connect(self._assay_changed)
        self.duration = QComboBox()
        self.duration.setEditable(True)
        self.duration.setValidator(QDoubleValidator(0.1, 1440, 2))
        self.duration.setMinimumWidth(80)
        self.duration.setToolTip("Pick a length or type any number of minutes.")
        self.start_btn = QPushButton("●  Start recording")
        self.start_btn.setStyleSheet("QPushButton{font-weight:bold; padding:6px 14px;}")
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setStyleSheet("QPushButton{padding:6px 14px;}")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet("font-size:16px; font-family:monospace;")
        self.disk_label = QLabel("")

        top = QHBoxLayout()
        top.addWidget(QLabel("Experiment:"))
        top.addWidget(self.assay_combo)
        top.addSpacing(12)
        top.addWidget(QLabel("Length (min):"))
        top.addWidget(self.duration)
        top.addSpacing(12)
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addSpacing(12)
        top.addWidget(self.timer_label)
        top.addStretch(1)
        top.addWidget(self.disk_label)

        # ---- left: session + animals
        self.session_box = QGroupBox("Session")
        sform = QFormLayout(self.session_box)
        self.experimenter = QLineEdit(settings.get("last_experimenter", ""))
        self.cohort = QLineEdit(settings.get("last_cohort", ""))
        sform.addRow("Experimenter *", self.experimenter)
        sform.addRow("Cohort", self.cohort)
        self.out_label = QLabel("")
        self.out_label.setWordWrap(True)
        self.out_label.setStyleSheet("color:#555;")
        sform.addRow("Saving to", self.out_label)

        self.forms_holder = QVBoxLayout()
        left_inner = QWidget()
        left_lay = QVBoxLayout(left_inner)
        left_lay.addWidget(self.session_box)
        left_lay.addLayout(self.forms_holder)
        left_lay.addStretch(1)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setWidget(left_inner)
        left.setMinimumWidth(300)

        # ---- right: camera grid
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 0, 0, 0)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.grid_w)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 1000])

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)

        self.tick = QTimer(self)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start(50)
        self.disk_tick = QTimer(self)
        self.disk_tick.timeout.connect(self._update_disk)
        self.disk_tick.start(5000)

        self.reload()

    # ----------------------------------------------------------- setup
    def reload(self) -> None:
        """Rebuild after settings changed (assays, slots, animal list...)."""
        self.animals = []
        if animals_path().exists():
            try:
                self.animals = records.load_animal_list(animals_path())
            except (OSError, UnicodeDecodeError):
                self.animals = []
        current = self.assay_combo.currentText() or self.settings.get("last_assay", "")
        self.assay_combo.blockSignals(True)
        self.assay_combo.clear()
        for a in self.settings.assays:
            self.assay_combo.addItem(a["name"])
        i = self.assay_combo.findText(current)
        self.assay_combo.setCurrentIndex(max(0, i))
        self.assay_combo.blockSignals(False)
        self._assay_changed(self.assay_combo.currentText())

    def activate(self) -> None:
        """Called when the tab becomes visible: make sure feeds are open."""
        self._open_cameras()

    def current_assay(self) -> dict | None:
        return self.settings.assay(self.assay_combo.currentText())

    def _assay_changed(self, name: str) -> None:
        assay = self.settings.assay(name)
        if assay is None:
            return
        self.settings["last_assay"] = name
        self.settings.save()

        # durations
        self.duration.clear()
        for d in assay.get("durations", []):
            self.duration.addItem(f"{d:g}")
        self.duration.setCurrentText(f"{assay.get('default_duration', 10):g}")

        # animal forms
        old_values = {k: f.values() for k, f in self.forms.items()}
        for f in self.forms.values():
            f.setParent(None)
            f.deleteLater()
        self.forms.clear()
        multi = len(assay["arenas"]) > 1
        for arena in assay["arenas"]:
            form = AnimalForm(arena["name"], multi, self.animals)
            if arena["name"] in old_values:
                form.set_values(old_values[arena["name"]])
            form.toggled.connect(self._arena_toggled)
            self.forms_holder.addWidget(form)
            self.forms[arena["name"]] = form

        # camera views
        for v in self.views.values():
            v.setParent(None)
            v.deleteLater()
        self.views.clear()
        self.view_slot.clear()
        self.view_arena.clear()
        cams = [(arena["name"], c) for arena in assay["arenas"] for c in arena["cameras"]]
        cols = 2 if len(cams) > 1 else 1
        for i, (arena_name, c) in enumerate(cams):
            slot = self.settings.slot(c["slot"]) or {"name": c["slot"]}
            view = CameraView(f"{c['label']}  ({slot['name']})")
            cs = self.settings.camera_settings(name, c["slot"])
            view.toggle.setChecked(cs["enabled"])
            view.enabled_changed.connect(lambda on, s=c["slot"]: self._camera_toggled(s, on))
            view.controls_requested.connect(lambda s=c["slot"]: self._open_controls(s))
            self.grid.addWidget(view, i // cols, i % cols)
            self.views[c["label"]] = view
            self.view_slot[c["label"]] = c["slot"]
            self.view_arena[c["label"]] = arena_name
        self.set_locked(self.settings.get("locked", False))
        self._open_cameras()
        self._update_out_label()
        self._update_disk()
        self._update_off_state()

    def _open_cameras(self) -> None:
        assay = self.current_assay()
        if assay is None:
            return
        needed = set()
        for label, view in self.views.items():
            slot_id = self.view_slot[label]
            controls = effective_controls(
                self.settings.camera_settings(assay["name"], slot_id)["controls"])
            dev = self.cameras.device_for_slot(slot_id)
            if dev is None:
                slot = self.settings.slot(slot_id)
                msg = ("Not assigned - choose a camera in Settings ▸ Cameras"
                       if not (slot and slot.get("device"))
                       else "Assigned camera is not connected")
                view.set_worker(None, msg)
                continue
            needed.add(dev.id)
            view.set_worker(self.cameras.worker(dev, controls))
        if not self.is_recording:
            self.cameras.keep_only(needed)

    def set_locked(self, locked: bool) -> None:
        for v in self.views.values():
            v.gear.setEnabled(not locked and not self.is_recording)
            v.toggle.setEnabled(not locked and not self.is_recording)

    def _camera_toggled(self, slot_id: str, on: bool) -> None:
        assay = self.current_assay()
        if assay:
            self.settings.camera_settings(assay["name"], slot_id)["enabled"] = on
            self.settings.save()
        self._update_off_state()

    def _arena_toggled(self, _on: bool) -> None:
        self._update_off_state()

    def _update_off_state(self) -> None:
        for label, view in self.views.items():
            view.set_off(not self._camera_will_record(label))

    def _camera_will_record(self, label: str) -> bool:
        form = self.forms.get(self.view_arena.get(label, ""))
        return bool(form and form.active and self.views[label].toggle.isChecked())

    def _open_controls(self, slot_id: str) -> None:
        assay = self.current_assay()
        if assay is None:
            return
        worker = self.cameras.worker_for_slot(slot_id)
        dlg = CameraControlsDialog(self.settings, assay["name"], slot_id, worker, self)
        dlg.exec()

    # --------------------------------------------------------- helpers
    def output_dir(self, assay: dict, when: datetime) -> Path:
        base = Path(self.settings["base_path"]) / assay["folder"]
        if self.settings.get("date_subfolders", True):
            base = base / when.strftime("%Y-%m-%d")
        return base

    def _update_out_label(self) -> None:
        assay = self.current_assay()
        if assay:
            self.out_label.setText(str(self.output_dir(assay, datetime.now())))

    def _update_disk(self) -> None:
        free = free_space_gb(self.settings["base_path"])
        if free is None:
            self.disk_label.setText("")
            return
        warn = free < float(self.settings.get("disk_warning_gb", 20))
        color = "#c00" if warn else "#555"
        self.disk_label.setText(f"<span style='color:{color}'>Free disk: {free:,.0f} GB"
                                f"{'  ⚠ low' if warn else ''}</span>")

    @property
    def is_recording(self) -> bool:
        return self.session is not None

    def _duration_minutes(self) -> float | None:
        try:
            v = float(self.duration.currentText())
        except ValueError:
            return None
        return v if v > 0 else None

    # ------------------------------------------------------- recording
    def start_recording(self) -> None:
        if self.is_recording:
            return
        assay = self.current_assay()
        if assay is None:
            return
        problems = []
        minutes = self._duration_minutes()
        if minutes is None:
            problems.append("Enter a recording length in minutes.")
        session_info = {"experimenter": self.experimenter.text().strip(),
                        "cohort": self.cohort.text().strip()}
        if not session_info["experimenter"]:
            problems.append("Experimenter is required.")

        arenas: dict[str, dict] = {}
        for name, form in self.forms.items():
            if not form.active:
                continue
            vals = form.values()
            for key, label, required in records.ANIMAL_FIELDS:
                if required and not vals.get(key):
                    problems.append(f"{name}: {label} is required.")
            arenas[name] = vals
        if not arenas:
            problems.append("Select at least one arena to record.")

        jobs: list[CameraJob] = []
        camera_problem_arenas = set()
        for label, view in self.views.items():
            arena = self.view_arena[label]
            if arena not in arenas or not view.toggle.isChecked():
                continue
            w = view.worker
            if w is None:
                problems.append(f"{label}: no camera assigned/connected.")
                camera_problem_arenas.add(arena)
            elif not w.healthy:
                problems.append(f"{label}: camera is not delivering frames.")
                camera_problem_arenas.add(arena)
            else:
                jobs.append(CameraJob(label, arena, self.view_slot[label], w))
        for name in arenas:
            if name not in camera_problem_arenas and not any(j.arena == name for j in jobs):
                problems.append(f"{name}: all of its cameras are switched off.")

        now = datetime.now()
        out_dir = self.output_dir(assay, now)
        if minutes and jobs:
            need_gb = len(jobs) * minutes * MB_PER_MIN_PER_CAMERA / 1000
            free = free_space_gb(self.settings["base_path"])
            if free is not None and free < need_gb * 1.2:
                problems.append(f"Not enough disk space: about {need_gb:.1f} GB needed, "
                                f"{free:.1f} GB free.")
        if problems:
            QMessageBox.warning(self, "Cannot start recording", "\n".join(problems))
            return
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Cannot start recording",
                                 f"Could not create output folder:\n{out_dir}\n\n{e}\n\n"
                                 "Check the base folder in Settings.")
            return

        self.settings["last_experimenter"] = session_info["experimenter"]
        self.settings["last_cohort"] = session_info["cohort"]
        self.settings.save()

        encoder = self.encoder.get()
        session = RecordingSession(
            jobs=jobs, out_dir=out_dir, start_time=now, duration_s=minutes * 60,
            encoder=encoder, quality=int(self.settings.get("quality", 20)),
            overlay=dict(self.settings.get("overlay", {})),
        )
        try:
            session.start()
        except Exception as e:  # noqa: BLE001 - show any startup failure to the user
            QMessageBox.critical(self, "Cannot start recording", f"Recording failed to start:\n{e}")
            return
        self.session = session
        self.session_meta = {
            "assay": assay, "arenas": arenas, "session_info": session_info,
            "minutes": minutes, "encoder": encoder,
            "camera_settings": {j.slot_id: self.settings.camera_settings(assay["name"], j.slot_id)
                                for j in jobs},
        }
        for label, v in self.views.items():
            v.set_recording(any(j.label == label for j in jobs))
        self._set_controls_enabled(False)
        self.recording_changed.emit(True)

    def stop_recording(self) -> None:
        if self.session and self.session.running:
            if QMessageBox.question(
                self, "Stop recording?",
                "Stop now? The videos recorded so far are kept and the trial is "
                "logged as stopped early.") == QMessageBox.StandardButton.Yes:
                self.session.request_stop()

    def _set_controls_enabled(self, on: bool) -> None:
        self.assay_combo.setEnabled(on)
        self.duration.setEnabled(on)
        self.start_btn.setEnabled(on)
        self.stop_btn.setEnabled(not on)
        self.session_box.setEnabled(on)
        for f in self.forms.values():
            f.setEnabled(on)
        self.set_locked(self.settings.get("locked", False))

    def _on_tick(self) -> None:
        s = self.session
        for label, view in self.views.items():
            extra = ""
            if s is not None and label in s.repeats:
                n = s.repeats[label]
                color = "#c00" if n else "#080"
                extra = f"  |  <span style='color:{color}'>repeated frames: {n}</span>"
            view.refresh(extra)
        if s is None:
            self.timer_label.setText("")
            return
        total = s.total_frames / OUTPUT_FPS
        el = s.elapsed_s
        if s.running:
            self.timer_label.setText(
                f"<span style='color:#d00'>● REC</span> {format_elapsed(el)[:-3]} / "
                f"{format_elapsed(total)[:-3]}   remaining {format_elapsed(max(0, total - el))[:-3]}")
        elif not self.finalizing:
            self.finalizing = True
            self.timer_label.setText("Saving videos…")
            self.stop_btn.setEnabled(False)
            threading.Thread(target=self._finalize_worker, args=(s,), daemon=True).start()

    def _finalize_worker(self, s: RecordingSession) -> None:
        try:
            results = s.finalize()
            m = self.session_meta
            info_files, log_ok = records.write_trial_records(
                assay=m["assay"], out_dir=s.out_dir, stamp=s.stamp,
                session_info=m["session_info"], arenas=m["arenas"], results=results,
                duration_set_min=m["minutes"], duration_actual_s=s.elapsed_s,
                stopped_early=s.stopped_early, start_wall=s.start_wall, encoder=m["encoder"],
                camera_settings=m["camera_settings"],
                master_log=Path(self.settings["base_path"]) / m["assay"]["folder"]
                / f"{m['assay']['folder']}_log.csv",
            )
            self._finisher.finished.emit((s, results, log_ok, None))
        except Exception as e:  # noqa: BLE001
            self._finisher.finished.emit((s, [], False, e))

    def _on_finalized(self, payload) -> None:
        s, results, log_ok, err = payload
        self.session = None
        self.finalizing = False
        for v in self.views.values():
            v.set_recording(False)
        self._set_controls_enabled(True)
        self.recording_changed.emit(False)
        self._open_cameras()

        lines = [f"<b>{self.session_meta['assay']['name']}</b> - started {s.stamp}",
                 f"Length: {format_elapsed(s.elapsed_s)[:-3]}"
                 + ("  <b style='color:#b60'>(stopped early)</b>" if s.stopped_early else ""),
                 f"Folder: {s.out_dir}", ""]
        any_repeat = False
        any_error = bool(err)
        for r in results:
            status = "OK"
            if r.repeated:
                any_repeat = True
                pct = 100 * r.repeated / max(1, r.frames)
                status = (f"<b style='color:#c00'>{r.repeated} repeated frame(s) "
                          f"({pct:.2f}%)</b>")
            if r.error:
                any_error = True
                status += f" <b style='color:#c00'>ERROR: {r.error}</b>"
            name = r.video.name if r.video else "(no file)"
            lines.append(f"{name}: {r.frames} frames - {status}")
        if err:
            lines.append(f"<b style='color:#c00'>Error while saving: {err}</b>")
        if not log_ok and not err:
            lines.append("<br><b style='color:#b60'>The master log was open in another program "
                         "(Excel?). This trial was saved to a _pending.csv file and will be "
                         "added to the log automatically next time.</b>")
        if any_repeat:
            lines.append("<br>Repeated frames mean a camera did not deliver a new frame in time; "
                         "the previous frame was written so timing stays correct. Their frame "
                         "numbers are listed in the _frames.csv / _info.json files and marked "
                         "with * in the video.")
        text = "<br>".join(lines)
        box = QMessageBox(self)
        box.setWindowTitle("Recording finished" + (" - with warnings" if any_repeat or any_error else ""))
        box.setIcon(QMessageBox.Icon.Warning if any_repeat or any_error or not log_ok
                    else QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.exec()
        for form in self.forms.values():
            if form.active:
                form.clear_for_next_animal()
        self._update_disk()
        self._update_out_label()
