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

    rec.assay_combo.setCurrentText("Elevated Plus")
    assert list(rec.views) == ["Overhead"]
    assert list(rec.forms) == ["EPM"]

    win.tabs.setCurrentIndex(1)
    app.processEvents()
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    win.cameras.shutdown()
    win.close()
