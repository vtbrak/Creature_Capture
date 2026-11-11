"""Smoke test: build the main window with test-pattern cameras (offscreen)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_CAPTURE_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_main_window_with_sim_cameras(app, tmp_path):
    from creature_capture.app import MainWindow
    from creature_capture.config import Settings

    s = Settings.load()
    s["simulated_cameras"] = 5
    s["base_path"] = str(tmp_path / "videos")
    sim_ids = [f"sim:{i}" for i in range(5)]
    for slot, sid in zip(s.slots, sim_ids):
        slot["device"] = {"id": sid, "name": sid}
    s.assays.append({"name": "Novel Object", "standard_assay": "Object Recognition",
                     "folder": "NovelObject", "durations": [10], "default_duration": 10,
                     "arenas": [{"name": "NOR1", "cameras": [{"slot": "Camera5",
                                                              "label": "Overhead"}]}]})
    s.save()

    win = MainWindow(s)
    win.show()
    rec = win.record
    assert len(rec.views) == 4  # open field
    deadline = time.time() + 3
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert all(v.worker is not None and v.worker.healthy for v in rec.views.values())

    rec.forms["Arena2"].setChecked(False)
    assert not rec._camera_will_record("Arena2_Overhead")
    assert rec._camera_will_record("Arena1_Overhead")
    # Cameras that won't be recorded are greyed out, the others are not.
    assert rec.views["Arena2_Overhead"]._off and rec.views["Arena2_Horizontal"]._off
    assert not rec.views["Arena1_Overhead"]._off
    assert rec.views["Arena2_Overhead"].image.styleSheet() == rec.views["Arena2_Overhead"].OFF_STYLE
    rec.views["Arena1_Horizontal"].toggle.setChecked(False)  # one camera switched off
    assert rec.views["Arena1_Horizontal"]._off
    rec.views["Arena1_Horizontal"].toggle.setChecked(True)
    assert not rec.views["Arena1_Horizontal"]._off
    assert "90" in [rec.duration.itemText(i) for i in range(rec.duration.count())]
    rec.reload()
    assert not rec.forms["Arena2"].active  # an arena switched off stays off
    assert not rec._camera_will_record("Arena2_Overhead")

    rec.assay_combo.setCurrentText("Elevated Plus")
    assert list(rec.views) == ["Overhead"]
    assert list(rec.forms) == ["EPM"]
    # One session per trial day: Trial day only, as a pick-or-type list.
    epm = rec.forms["EPM"].fields
    assert "trial_day" in epm and "session_number" not in epm
    day_choices = [epm["trial_day"].itemText(i) for i in range(epm["trial_day"].count())]
    assert day_choices == [""] + [str(n) for n in range(1, 11)]

    # Puzzle Box has sessions within a day: same Trial day list, plus Session that day.
    rec.assay_combo.setCurrentText("Puzzle Box")
    pb = rec.forms["PuzzleBox"]
    assert [pb.fields[k].itemText(i) for k in ("trial_day", "session_number")
            for i in range(pb.fields[k].count())] == day_choices * 2
    pb.fields["trial_day"].setCurrentText("3")
    pb.fields["session_number"].setCurrentText("12")  # typing a number not in the list
    assert (pb.values()["trial_day"], pb.values()["session_number"]) == ("3", "12")
    rec.assay_combo.setCurrentText("Elevated Plus")
    assert not rec.variant.isVisibleTo(rec) and not rec.phase.isVisibleTo(rec)
    assert rec.forms["EPM"].objects is None

    rec.assay_combo.setCurrentText("Novel Object")
    assert rec.variant.isVisibleTo(rec) and rec.phase.isVisibleTo(rec)
    assert [rec.variant.itemText(i) for i in range(rec.variant.count())] == [
        "", "Novel Object Recognition", "Spatial Object Recognition"]
    assert [rec.phase.itemText(i) for i in range(rec.phase.count())] == [
        "", "Habituation", "Training", "Test"]
    form = rec.forms["NOR1"]
    assert form.objects is not None and form.objects.rowCount() == 2
    form.objects.item(0, 0).setText("glass bottle")
    form.objects.cellWidget(0, 1).setCurrentText("Novel")
    assert form.values()["objects"] == [
        {"identity": "glass bottle", "kind": "Novel", "position": ""}]

    # Coming back from Settings rebuilds the tab: what was typed must survive.
    form.fields["animal_id"].setText("M7")
    form.fields["notes"].setPlainText("sleepy")
    rec.phase.setCurrentText("Test")
    rec.reload()
    form = rec.forms["NOR1"]
    assert form.values()["animal_id"] == "M7" and form.values()["notes"] == "sleepy"
    assert form.values()["objects"] == [
        {"identity": "glass bottle", "kind": "Novel", "position": ""}]
    assert form.objects.rowCount() == 2 and rec.phase.currentText() == "Test"

    # Greyed out also when no camera is assigned to the position.
    rec.assay_combo.setCurrentText("Open Field")
    s.slot("Arena2_Overhead")["device"] = None
    rec.reload()
    rec.forms["Arena2"].setChecked(False)
    v = rec.views["Arena2_Overhead"]
    assert v.worker is None and v._off and v.image.text().startswith("NOT RECORDING")
    rec.forms["Arena2"].setChecked(True)
    assert not v._off and not v.image.text().startswith("NOT RECORDING")

    win.tabs.setCurrentIndex(1)
    app.processEvents()
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    win.cameras.shutdown()
    win.close()


def test_assay_editor_labels_and_names(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

    from creature_capture.config import Settings
    from creature_capture.ui.assay_editor import AssayEditor

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    s = Settings.load(tmp_path / "s.json")
    ed = AssayEditor(s, s.assay("Open Field"))
    assert ed.table.item(0, 2).text() == "Overhead"  # shown without the arena
    assert ed.std_assay.currentData() == "Open Field"
    ed.accept()
    assert not warnings
    cams = [c["label"] for a in ed.result_assay["arenas"] for c in a["cameras"]]
    assert cams == ["Arena1_Overhead", "Arena1_Horizontal", "Arena2_Overhead", "Arena2_Horizontal"]
    assert ed.result_assay["standard_assay"] == "Open Field"
    assert ed.result_assay["multiple_sessions"] is False

    ed = AssayEditor(s, s.assay("Puzzle Box"))
    assert ed.std_assay.currentData() == "Puzzle Box" and ed.sessions.isChecked()
    ed.std_assay.setCurrentIndex(ed.std_assay.findData("Open Field"))
    assert not ed.sessions.isChecked()  # follows the assay type, and can still be changed

    ed = AssayEditor(s, s.assay("Elevated Plus"))
    ed.table.setItem(0, 2, QTableWidgetItem("Top_view"))
    ed.accept()
    assert warnings and "only letters, digits and -" in warnings[-1]
    assert ed.result_assay is None


def test_camera_controls_manual_and_auto(app, tmp_path):
    from creature_capture.config import Settings
    from creature_capture.ui.camera_controls import CameraControlsDialog

    s = Settings.load(tmp_path / "s.json")
    dlg = CameraControlsDialog(s, "Open Field", "Arena1_Overhead", None)
    shown = lambda key: not dlg.sliders[key].isHidden()  # noqa: E731

    # Defaults: exposure under manual control with auto off, so its slider is shown.
    assert dlg.manual["auto_exposure"].isChecked() and dlg.auto_off["auto_exposure"].isChecked()
    assert shown("exposure") and dlg.spins["exposure"].value() == -5
    assert "exposure" not in dlg.manual and "wb_temperature" not in dlg.manual  # no box of their own
    # White balance is left to the camera: no auto choice, no slider.
    assert not dlg.manual["auto_wb"].isChecked()
    assert dlg.auto_choice["auto_wb"].isHidden() and not shown("wb_temperature")
    # Other sliders can be dragged only under manual control.
    assert not dlg.sliders["gain"].isEnabled()
    dlg.manual["gain"].setChecked(True)
    assert dlg.sliders["gain"].isEnabled()
    dlg.spins["gain"].setValue(12)

    # Auto on hides the slider; only one of Auto on / Auto off can be chosen.
    dlg.auto_on["auto_exposure"].setChecked(True)
    assert not dlg.auto_off["auto_exposure"].isChecked() and not shown("exposure")
    c = dlg._collect()
    assert c["auto_exposure"] == {"apply": True, "value": 1} and not c["exposure"]["apply"]
    assert "not locked off" in dlg.exposure_warn.text()

    # Manual white balance with auto off shows its slider.
    dlg.manual["auto_wb"].setChecked(True)
    assert not dlg.auto_choice["auto_wb"].isHidden() and shown("wb_temperature")
    dlg.spins["wb_temperature"].setValue(5000)

    # Giving exposure back to the camera removes the choice and the slider.
    dlg.manual["auto_exposure"].setChecked(False)
    assert dlg.auto_choice["auto_exposure"].isHidden() and not shown("exposure")

    dlg.accept()
    saved = s.camera_settings("Open Field", "Arena1_Overhead")["controls"]
    assert saved["auto_exposure"]["apply"] is False and saved["exposure"]["apply"] is False
    assert saved["auto_wb"] == {"apply": True, "value": 0}
    assert saved["wb_temperature"] == {"apply": True, "value": 5000}
    assert saved["gain"] == {"apply": True, "value": 12}
    assert list(saved) == ["auto_exposure", "exposure", "gain", "brightness", "contrast", "gamma",
                           "sharpness", "auto_wb", "wb_temperature"]

    # Reopening shows what was saved. A manual exposure saved without its auto mode
    # (possible in the old window) is shown as manual control, auto off.
    saved["exposure"] = {"apply": True, "value": -7}
    dlg = CameraControlsDialog(s, "Open Field", "Arena1_Overhead", None)
    assert dlg.manual["auto_exposure"].isChecked() and dlg.auto_off["auto_exposure"].isChecked()
    assert dlg.spins["exposure"].value() == -7 and dlg.spins["wb_temperature"].value() == 5000
    assert dlg.exposure_warn.text() == ""
    dlg.reject()


def test_camera_controls_in_the_cameras_table(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QPushButton

    from creature_capture.app import MainWindow
    from creature_capture.config import Settings
    from creature_capture.ui import settings_tab

    s = Settings.load()
    s["base_path"] = str(tmp_path / "videos")
    win = MainWindow(s)
    st = win.settings_tab
    opened = []

    class FakeDialog:
        def __init__(self, settings, assay_name, slot_id, worker, parent):
            opened.append((assay_name, slot_id, worker))

        def exec(self):
            return 0

    monkeypatch.setattr(settings_tab, "CameraControlsDialog", FakeDialog)

    # Every camera position has its controls button in the row where it is assigned.
    buttons = [st.slot_table.cellWidget(r, 2) for r in range(st.slot_table.rowCount())]
    assert len(buttons) == 5 and all(isinstance(b, QPushButton) for b in buttons)

    # Used by one experiment: opens straight away, and selects that row for the preview.
    buttons[1].click()
    assert opened == [("Open Field", "Arena1_Horizontal", None)]  # no camera assigned in this test
    assert st.slot_table.currentRow() == 1

    # Camera 5 is used by two experiments: it asks which.
    assert st._experiments_for("Camera5") == (["Elevated Plus", "Puzzle Box"], True)
    monkeypatch.setattr(st, "_choose_experiment", lambda slot_id, button: "Puzzle Box")
    buttons[4].click()
    assert opened[-1] == ("Puzzle Box", "Camera5", None)
    monkeypatch.setattr(st, "_choose_experiment", lambda slot_id, button: None)  # menu dismissed
    buttons[4].click()
    assert len(opened) == 2

    # A newly added camera position gets its controls too, for any experiment.
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Arena 3 Overhead", True))
    st._add_slot()
    assert st.slot_table.rowCount() == 6
    new_button = st.slot_table.cellWidget(5, 2)
    assert isinstance(new_button, QPushButton)
    assert st._experiments_for("Arena3Overhead") == (
        ["Open Field", "Elevated Plus", "Puzzle Box"], False)
    monkeypatch.setattr(st, "_choose_experiment", lambda slot_id, button: "Open Field")
    new_button.click()
    assert opened[-1] == ("Open Field", "Arena3Overhead", None)
    # ... and starts from the standard defaults (manual exposure, auto off, -5).
    from creature_capture.camera import effective_controls
    c = effective_controls(s.camera_settings("Open Field", "Arena3Overhead")["controls"])
    assert c["auto_exposure"] == {"apply": True, "value": 0} and c["exposure"]["value"] == -5

    # Locking the settings locks the buttons with the rest of the table.
    st.lock.setChecked(True)
    assert not st.slot_table.cellWidget(0, 2).isEnabled()
    win.cameras.shutdown()
    win.close()
