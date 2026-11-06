"""Animal / session information, per-trial info files and master logs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from creature_capture import __version__
from creature_capture.camera import effective_controls

ANIMAL_FIELDS = [
    ("animal_id", "Animal ID", True),
    ("sex", "Sex", False),
    ("strain", "Strain / genotype", False),
    ("dob", "DOB", False),
    ("treatment", "Treatment / group", False),
    ("trial_day", "Trial / day", False),
    ("notes", "Notes", False),
]
SESSION_FIELDS = [
    ("experimenter", "Experimenter", True),
    ("cohort", "Cohort / litter", False),
]

LOG_COLUMNS = [
    "date", "start_time", "assay", "arena",
    "experimenter", "cohort",
    "animal_id", "sex", "strain", "dob", "treatment", "trial_day", "notes",
    "duration_set_min", "duration_actual_s", "stopped_early",
    "frames", "repeated_frames", "videos", "encoder", "app_version",
]


def safe_name(text: str) -> str:
    keep = "-_."
    return "".join(c if c.isalnum() or c in keep else "_" for c in text).strip("_")


# ------------------------------------------------------------- animal list
_ALIASES = {
    "animal_id": {"animal_id", "animal id", "id", "animal", "mouse", "mouse id", "rat id", "subject"},
    "sex": {"sex", "gender"},
    "strain": {"strain", "genotype", "strain/genotype", "strain / genotype", "line"},
    "dob": {"dob", "date of birth", "birth date", "birthdate"},
    "treatment": {"treatment", "group", "treatment/group", "treatment / group", "condition"},
}


def load_animal_list(path: Path) -> list[dict]:
    """Read a CSV of animals; column names are matched loosely."""
    animals = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        mapping = {}
        for col in reader.fieldnames or []:
            norm = col.strip().lower()
            for key, names in _ALIASES.items():
                if norm in names and key not in mapping.values():
                    mapping[col] = key
        for row in reader:
            a = {key: (row.get(col) or "").strip() for col, key in mapping.items()}
            if a.get("animal_id"):
                animals.append(a)
    return animals


# ------------------------------------------------------------- trial files
def write_trial_records(
    *,
    assay: dict,
    out_dir: Path,
    stamp: str,
    session_info: dict,
    arenas: dict[str, dict],  # arena name -> animal info
    results: list,  # CameraResult list
    duration_set_min: float,
    duration_actual_s: float,
    stopped_early: bool,
    start_wall,
    encoder: str,
    camera_settings: dict,
    master_log: Path,
) -> tuple[list[Path], bool]:
    """Write <stamp>_<arena>_info.csv/.json next to the videos and append to
    the assay's master log. Returns (info files written, master log updated)."""
    written = []
    log_ok = True
    date_s, time_s = stamp.split("_", 1)
    time_s = time_s.replace("-", ":")
    for arena_name, animal in arenas.items():
        arena_results = [r for r in results if r.arena == arena_name]
        videos = [r.video.name for r in arena_results if r.video]
        repeated = ";".join(f"{r.label}:{r.repeated}" for r in arena_results)
        row = {
            "date": date_s,
            "start_time": time_s,
            "assay": assay["name"],
            "arena": arena_name,
            "experimenter": session_info.get("experimenter", ""),
            "cohort": session_info.get("cohort", ""),
            **{k: animal.get(k, "") for k, _, _ in ANIMAL_FIELDS},
            "duration_set_min": f"{duration_set_min:g}",
            "duration_actual_s": f"{duration_actual_s:.2f}",
            "stopped_early": "yes" if stopped_early else "no",
            "frames": arena_results[0].frames if arena_results else 0,
            "repeated_frames": repeated,
            "videos": ";".join(videos),
            "encoder": encoder,
            "app_version": __version__,
        }
        base = out_dir / f"{stamp}_{safe_name(arena_name)}_info"
        csv_path = base.with_suffix(".csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            w.writeheader()
            w.writerow(row)
        written.append(csv_path)

        detail = {
            **row,
            "start_wall_clock": start_wall.isoformat(timespec="milliseconds") if start_wall else None,
            "cameras": [
                {
                    "label": r.label,
                    "slot": r.slot_id,
                    "video": r.video.name if r.video else None,
                    "timestamps_csv": r.timestamps.name if r.timestamps else None,
                    "frames": r.frames,
                    "verified_frames_in_file": r.verified_frames,
                    "repeated_frames": r.repeated,
                    "repeated_frame_indices": r.repeated_frames,
                    "error": r.error,
                    "camera_settings": _applied_settings(camera_settings.get(r.slot_id)),
                }
                for r in arena_results
            ],
        }
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(detail, indent=2), encoding="utf-8")
        written.append(json_path)

        log_ok = append_master_log(master_log, row) and log_ok
    return written, log_ok


def _applied_settings(saved: dict | None) -> dict:
    """Camera settings as used in the trial: every control, with the built-in
    defaults filled in for any the user never saved. ``apply: false`` means the
    camera was left at its own value for that control."""
    saved = saved or {}
    return {"enabled": saved.get("enabled", True),
            "controls": effective_controls(saved.get("controls"))}


def _append_rows(path: Path, rows: list[dict]) -> None:
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def append_master_log(path: Path, row: dict) -> bool:
    """Append a row to the master log.

    If the log is open in Excel (Windows locks it), the row goes into a
    "_pending.csv" file instead and is merged in automatically next time.
    Returns False if the row had to be parked in the pending file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.stem + "_pending.csv")
    rows = []
    if pending.exists():
        with open(pending, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    rows.append(row)
    try:
        _append_rows(path, rows)
    except PermissionError:
        try:
            pending.unlink(missing_ok=True)
            _append_rows(pending, rows)
        except OSError:
            pass
        return False
    pending.unlink(missing_ok=True)
    return True
