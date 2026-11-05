import csv
import json
import time
from datetime import datetime

import numpy as np
import pytest

from creature_capture import devices, records
from creature_capture.config import Settings
from creature_capture.recorder import CameraJob, RecordingSession, draw_overlay, format_elapsed


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_CAPTURE_HOME", str(tmp_path / "home"))


NEW_FORMAT = r'''
[dshow @ 000001] "USB Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\?\usb#vid_32e4&pid_9230&mi_00#7&1a2b3c4d&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global"
[dshow @ 000001] "USB Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\?\usb#vid_32e4&pid_9230&mi_00#7&5e6f7a8b&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global"
[dshow @ 000001] "Microphone (Realtek)" (audio)
[dshow @ 000001]   Alternative name "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\wave_{ABC}"
dummy: Immediate exit requested
'''

OLD_FORMAT = r'''
[dshow @ 0000] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0000]  "ELP Camera"
[dshow @ 0000]     Alternative name "@device_pnp_\\?\usb#vid_05a3&pid_9422#port1#{65e8773d}\global"
[dshow @ 0000] DirectShow audio devices
[dshow @ 0000]  "Mic"
[dshow @ 0000]     Alternative name "@device_cm_mic"
'''


def test_parse_dshow_new_format():
    devs = devices.parse_dshow_listing(NEW_FORMAT)
    assert len(devs) == 2
    assert devs[0][0] == "USB Camera"
    assert "7&1a2b3c4d" in devs[0][1]
    assert devs[0][1] != devs[1][1]


def test_parse_dshow_old_format():
    devs = devices.parse_dshow_listing(OLD_FORMAT)
    assert devs == [("ELP Camera", r"@device_pnp_\\?\usb#vid_05a3&pid_9422#port1#{65e8773d}\global")]


def test_settings_roundtrip(tmp_path):
    s = Settings.load(tmp_path / "s.json")
    assert [a["name"] for a in s.assays] == ["Open Field", "Elevated Plus", "Puzzle Box"]
    cs = s.camera_settings("Elevated Plus", "Camera5")
    cs["controls"]["gain"] = {"apply": True, "value": 12}
    s.save()
    s2 = Settings.load(tmp_path / "s.json")
    assert s2.camera_settings("Elevated Plus", "Camera5")["controls"]["gain"]["value"] == 12
    # separate settings per assay for the shared camera
    assert s2.camera_settings("Puzzle Box", "Camera5")["controls"] == {}


def test_overlay_only_touches_corner():
    frame = np.full((600, 800), 128, np.uint8)
    out = draw_overlay(frame, 4149, 20, True, {"font_scale": 0.5})
    changed = np.argwhere(out != frame)
    assert changed.size > 0
    assert changed[:, 0].max() < 40 and changed[:, 1].max() < 400
    assert format_elapsed(4149 / 20) == "00:03:27.45"


def test_animal_list_aliases(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("ID,Gender,Genotype,Date of Birth,Group\nM1,M,WT,2026-01-02,Saline\n,,,,\n")
    animals = records.load_animal_list(p)
    assert animals == [{"animal_id": "M1", "sex": "M", "strain": "WT", "dob": "2026-01-02",
                        "treatment": "Saline"}]


class _FakeWorker:
    """Delivers a new frame every call unless stalled."""

    def __init__(self, stall_after=None):
        self.seq = 0
        self.stall_after = stall_after
        self.t0 = time.perf_counter()

    def latest(self):
        if self.stall_after is None or self.seq < self.stall_after:
            self.seq += 1
        frame = np.full((600, 800), self.seq % 255, np.uint8)
        return frame, self.seq, time.perf_counter()


def _record(tmp_path, workers, seconds=2.0):
    jobs = [CameraJob(f"Cam{i}", "Arena1" if i < 2 else "Arena2", f"slot{i}", w)
            for i, w in enumerate(workers)]
    s = RecordingSession(jobs, tmp_path, datetime(2026, 11, 5, 14, 32, 7), seconds, "libx264", 23,
                         {"enabled": True})
    s.start()
    s.wait_clock()
    return s, s.finalize()


def test_recording_sync_and_counts(tmp_path):
    s, results = _record(tmp_path, [_FakeWorker(), _FakeWorker(), _FakeWorker()])
    assert not s.stopped_early
    assert {r.frames for r in results} == {40}
    for r in results:
        assert r.video.name == f"2026-11-05_14-32-07_{r.label}.mp4"
        assert r.verified_frames == 40
        assert r.repeated == 0
        assert not r.error
        rows = list(csv.DictReader(open(r.timestamps)))
        assert len(rows) == 40
    assert not list(tmp_path.glob("*.recording.mp4"))


def test_repeated_frames_reported(tmp_path):
    s, results = _record(tmp_path, [_FakeWorker(), _FakeWorker(stall_after=10)], seconds=1.0)
    good, stalled = results
    assert good.repeated == 0
    assert stalled.repeated == 10
    assert stalled.repeated_frames == list(range(10, 20))
    assert stalled.verified_frames == 20  # still full length: timing stays true


def test_stop_early(tmp_path):
    jobs = [CameraJob("Cam0", "Arena1", "s0", _FakeWorker())]
    s = RecordingSession(jobs, tmp_path, datetime.now(), 60, "libx264", 23, {})
    s.start()
    time.sleep(0.6)
    s.request_stop()
    results = s.finalize()
    assert s.stopped_early
    assert 5 < results[0].frames < 30
    assert results[0].verified_frames == results[0].frames


def test_trial_records_and_master_log(tmp_path):
    s, results = _record(tmp_path, [_FakeWorker(), _FakeWorker(), _FakeWorker()], seconds=0.5)
    settings = Settings.load(tmp_path / "s.json")
    log = tmp_path / "OpenField_log.csv"
    files, ok = records.write_trial_records(
        assay=settings.assay("Open Field"), out_dir=tmp_path, stamp=s.stamp,
        session_info={"experimenter": "ES", "cohort": "C1"},
        arenas={"Arena1": {"animal_id": "M1", "dob": "2026-01-01"}, "Arena2": {"animal_id": "M2"}},
        results=results, duration_set_min=10, duration_actual_s=s.elapsed_s,
        stopped_early=False, start_wall=s.start_wall, encoder="libx264",
        camera_settings={}, master_log=log)
    assert ok
    assert (tmp_path / "2026-11-05_14-32-07_Arena1_info.csv").exists()
    info = json.loads((tmp_path / "2026-11-05_14-32-07_Arena1_info.json").read_text())
    assert [c["label"] for c in info["cameras"]] == ["Cam0", "Cam1"]
    rows = list(csv.DictReader(open(log)))
    assert [r["animal_id"] for r in rows] == ["M1", "M2"]
    assert rows[0]["start_time"] == "14:32:07"
    assert rows[1]["videos"] == "2026-11-05_14-32-07_Cam2.mp4"
