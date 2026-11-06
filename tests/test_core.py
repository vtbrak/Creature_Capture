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
        assert r.video.name == f"2026-11-05_14-32-07_{r.arena}_{r.label}.mp4"
        assert r.verified_frames == 40
        assert r.repeated == 0
        assert not r.error
        rows = list(csv.DictReader(open(r.timestamps)))
        assert len(rows) == 40
        assert rows[0]["frame"] == "0" and rows[0]["repeated"] == "false"
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
        session_info={"experimenter": "ES", "cohort": "C1", "assay_variant": ""},
        arenas={"Arena1": {"animal_id": "M1", "dob": "2026-01-01", "sex": "Female",
                           "trial_day": "2", "session_number": "1", "strain": ""},
                "Arena2": {"animal_id": "M2", "sex": "Unknown"}},
        results=results, duration_set_min=10, duration_actual_s=s.elapsed_s,
        stopped_early=False, start_wall=s.start_wall, encoder="libx264",
        camera_settings={results[0].slot_id: {"enabled": True,
                                              "controls": {"gain": {"apply": True, "value": 12}}}},
        master_log=log)
    assert ok
    assert (tmp_path / "2026-11-05_14-32-07_Arena1_info.csv").exists()
    info = json.loads((tmp_path / "2026-11-05_14-32-07_Arena1_info.json").read_text())

    # Track Tamer metadata standard, schema 1
    assert info["schema_version"] == 1
    assert info["app_name"] == "Creature Capture"
    assert info["assay"] == "Open Field"
    assert info["arena"] == "Arena1"
    assert info["sex"] == "F"
    assert info["trial_day"] == 2 and info["session_number"] == 1
    assert info["duration_set_min"] == 10
    assert info["stopped_early"] is False
    assert info["date"] == "2026-11-05" and info["start_time"] == "14:32:07"
    assert "strain" not in info and "assay_variant" not in info  # unknown: left out, not ""
    assert "phase" not in info and "objects" not in info
    assert "start_wall_clock" not in info  # removed in the revised standard
    assert "frames" not in info and "videos" not in info  # read from cameras[]
    assert info["creature_capture"] == {"experiment": "Open Field", "gpu": False}

    cams = info["cameras"]
    assert [c["label"] for c in cams] == ["Cam0", "Cam1"]
    assert cams[0]["video"] == "2026-11-05_14-32-07_Arena1_Cam0.mp4"
    assert cams[0]["timestamps_csv"] == "2026-11-05_14-32-07_Arena1_Cam0_frames.csv"
    assert cams[0]["fps_set"] == 20 and cams[0]["fps_measured"] == 20.0
    assert (cams[0]["width_px"], cams[0]["height_px"]) == (800, 600)
    assert cams[0]["frames"] == cams[0]["verified_frames_in_file"] == 10
    assert cams[0]["repeated_frames"] == 0 and cams[0]["repeated_frame_indices"] == []
    assert "error" not in cams[0]  # left out when there's no error
    assert "slot" not in cams[0] and "creature_capture" not in cams[0]

    # camera_position and camera_settings are standard camera fields, always written.
    assert cams[0]["camera_position"] == "slot0"
    c0 = cams[0]["camera_settings"]
    assert c0["encoder"] == "libx264"
    assert c0["gain"] == {"apply": True, "value": 12}  # saved control kept
    assert c0["auto_exposure"] == {"apply": True, "value": 0}  # defaults filled in
    assert c0["exposure"] == {"apply": True, "value": -5}
    c1 = cams[1]["camera_settings"]  # nothing saved for this camera: every setting still written
    assert set(c1) == set(c0) and c1["gain"] == {"apply": False, "value": 0}

    info2 = json.loads((tmp_path / "2026-11-05_14-32-07_Arena2_info.json").read_text())
    assert info2["sex"] == "U"  # unknown or not recorded
    assert not list(tmp_path.glob("*.tmp"))

    rows = list(csv.DictReader(open(log)))
    assert [r["animal_id"] for r in rows] == ["M1", "M2"]
    assert rows[0]["start_time"] == "14:32:07"
    assert rows[1]["videos"] == "2026-11-05_14-32-07_Arena2_Cam2.mp4"


def test_standard_assay_names_and_object_recognition(tmp_path):
    settings = Settings.load(tmp_path / "s.json")
    from creature_capture.config import standard_assay
    assert standard_assay(settings.assay("Elevated Plus")) == "Elevated Plus Maze"
    assert standard_assay(settings.assay("Puzzle Box")) == ""
    # An experiment saved by 0.1.0 has no standard_assay key: mapped from its name.
    assert standard_assay({"name": "Elevated Plus"}) == "Elevated Plus Maze"
    assert standard_assay({"name": "open field"}) == "Open Field"

    s, results = _record(tmp_path, [_FakeWorker()], seconds=0.3)
    assay = {"name": "NOR", "standard_assay": "Object Recognition", "folder": "NOR",
             "arenas": [{"name": "Arena1", "cameras": []}]}
    records.write_trial_records(
        assay=assay, out_dir=tmp_path, stamp=s.stamp,
        session_info={"experimenter": "ES", "assay_variant": "Novel Object Recognition",
                      "phase": "Test"},
        arenas={"Arena1": {"animal_id": "M1", "objects": [
            {"identity": "glass bottle", "kind": "Familiar", "position": "top left"},
            {"identity": "lego tower", "kind": "Novel", "position": ""}]}},
        results=results, duration_set_min=5, duration_actual_s=s.elapsed_s,
        stopped_early=True, start_wall=s.start_wall, encoder="h264_nvenc",
        camera_settings={}, master_log=tmp_path / "NOR_log.csv")
    info = json.loads((tmp_path / "2026-11-05_14-32-07_Arena1_info.json").read_text())
    assert info["assay"] == "Object Recognition"
    assert info["assay_variant"] == "Novel Object Recognition"
    assert info["phase"] == "Test"
    assert info["objects"] == [
        {"name": "object 1", "identity": "glass bottle", "kind": "Familiar", "position": "top left"},
        {"name": "object 2", "identity": "lego tower", "kind": "Novel"}]
    assert info["stopped_early"] is True
    assert info["creature_capture"]["gpu"] is True
    assert info["cameras"][0]["camera_settings"]["encoder"] == "h264_nvenc"
    assert info["creature_capture"]["experiment"] == "NOR"


def test_old_master_log_header_upgraded(tmp_path):
    log = tmp_path / "OpenField_log.csv"
    old_cols = [c for c in records.LOG_COLUMNS
                if c not in ("assay_variant", "phase", "session_number")]
    with open(log, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        w.writerow({"date": "2026-11-01", "assay": "Open Field", "animal_id": "OLD1"})
    records.append_master_log(log, {"date": "2026-11-05", "assay": "Open Field",
                                    "assay_variant": "", "animal_id": "NEW1"})
    rows = list(csv.DictReader(open(log)))
    assert list(rows[0]) == records.LOG_COLUMNS
    assert [r["animal_id"] for r in rows] == ["OLD1", "NEW1"]


def test_phase_and_variant_only_from_the_assays_lists(tmp_path):
    s, results = _record(tmp_path, [_FakeWorker()], seconds=0.3)
    common = dict(out_dir=tmp_path, stamp=s.stamp, results=results, duration_set_min=5,
                  duration_actual_s=s.elapsed_s, stopped_early=False, start_wall=s.start_wall,
                  encoder="libx264", camera_settings={}, master_log=tmp_path / "log.csv")
    fc = {"name": "FC", "standard_assay": "Fear Conditioning", "folder": "FC", "arenas": []}
    records.write_trial_records(assay=fc, arenas={"Arena1": {"animal_id": "M1"}},
                                session_info={"phase": "Cue Test", "assay_variant": "Test"},
                                **common)
    info = json.loads((tmp_path / "2026-11-05_14-32-07_Arena1_info.json").read_text())
    assert info["phase"] == "Cue Test"
    assert "assay_variant" not in info  # Fear Conditioning has no variants
    of = {"name": "Open Field", "standard_assay": "Open Field", "folder": "OF", "arenas": []}
    records.write_trial_records(assay=of, arenas={"Arena1": {"animal_id": "M1"}},
                                session_info={"phase": "Test"}, **common)
    info = json.loads((tmp_path / "2026-11-05_14-32-07_Arena1_info.json").read_text())
    assert "phase" not in info  # Open Field has no phases


def test_camera_labels_in_file_names():
    from creature_capture.recorder import camera_label
    assert camera_label("Arena1_Overhead", "Arena1") == "Overhead"
    assert camera_label("Overhead", "EPM") == "Overhead"
    assert camera_label("Side view_2", "A") == "Side-view-2"
