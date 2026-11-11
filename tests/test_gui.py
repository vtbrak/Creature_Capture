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
