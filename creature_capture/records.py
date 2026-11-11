"""Animal / session information, per-trial info files and master logs."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

from creature_capture import APP_NAME, __version__
from creature_capture.camera import effective_controls
from creature_capture.config import (
    OUTPUT_FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH, assay_phases, assay_variants, standard_assay,
)
from creature_capture.recorder import arena_slug, camera_label

ANIMAL_FIELDS = [
    ("animal_id", "Animal ID", True),
    ("sex", "Sex", False),
    ("strain", "Strain / genotype", False),
    ("dob", "DOB", False),
    ("treatment", "Treatment / group", False),
    ("trial_day", "Trial day", False),
    ("session_number", "Session that day", False),  # only for experiments with sessions
    ("notes", "Notes", False),
]
LOG_COLUMNS = [
    "date", "start_time", "assay", "assay_variant", "phase", "arena",
    "experimenter", "cohort",
    "animal_id", "sex", "strain", "dob", "treatment", "trial_day", "session_number", "notes",
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
SCHEMA_VERSION = 1  # Track Tamer metadata standard (metadata_standard.md)


def _number(text):
    """"3" -> 3, "2.5" -> 2.5, "" -> None; other text is kept as text."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return text
    t = str(text).strip()
    if not t:
        return None
    try:
        f = float(t)
    except ValueError:
        return t
    return int(f) if f.is_integer() else f


def _sex(text: str) -> str:
    """F, M, or U (unknown or not recorded), per the metadata standard."""
    t = (text or "").strip().lower()
    if t in ("f", "female"):
        return "F"
    if t in ("m", "male"):
        return "M"
    return "U"


def _drop_empty(d: dict) -> dict:
    """The standard: leave unknown fields out instead of writing ""."""
    return {k: v for k, v in d.items() if v is not None and v != "" and v != []}


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
    encoder: str,
    camera_settings: dict,
    master_log: Path,
) -> tuple[list[Path], bool]:
    """Write <stamp>_<arena>_info.json (Track Tamer metadata standard, schema 1)
    and <stamp>_<arena>_info.csv next to the videos, and append to the
    experiment's master log. Returns (info files written, master log updated)."""
    written = []
    log_ok = True
    date_s, time_s = stamp.split("_", 1)
    assay_name = standard_assay(assay) or assay["name"]
    # Variant and phase only from that assay's own lists (standard, section 3).
    variant = session_info.get("assay_variant", "")
    phase = session_info.get("phase", "")
    for arena_name, animal in arenas.items():
        arena = arena_slug(arena_name)
        arena_results = [r for r in results if r.arena == arena_name]
        # The trial as text: the CSV row as it is, and the base of the JSON.
        trial = {
            "date": date_s,
            "start_time": time_s.replace("-", ":"),
            "assay": assay_name,
            "assay_variant": variant if variant in assay_variants(assay_name) else "",
            "phase": phase if phase in assay_phases(assay_name) else "",
            "arena": arena,
            "experimenter": session_info.get("experimenter", ""),
            "cohort": session_info.get("cohort", ""),
            **{k: animal.get(k, "") for k, _, _ in ANIMAL_FIELDS},
            "sex": _sex(animal.get("sex", "")),
        }
        row = {
            **trial,
            "duration_set_min": f"{duration_set_min:g}",
            "duration_actual_s": f"{duration_actual_s:.2f}",
            "stopped_early": "yes" if stopped_early else "no",
            "frames": arena_results[0].frames if arena_results else 0,
            "repeated_frames": ";".join(f"{camera_label(r.label, r.arena)}:{r.repeated}"
                                        for r in arena_results),
            "videos": ";".join(r.video.name for r in arena_results if r.video),
            "encoder": encoder,
            "app_version": __version__,
        }
        base = out_dir / f"{stamp}_{arena}_info"
        csv_path = base.with_suffix(".csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            w.writeheader()
            w.writerow(row)
        written.append(csv_path)

        # The JSON: same fields with JSON types, and blank ones left out.
        info = _drop_empty({
            "schema_version": SCHEMA_VERSION,
            "app_name": APP_NAME,
            "app_version": __version__,
            **trial,
            "trial_day": _number(trial["trial_day"]),
            "session_number": _number(trial["session_number"]),
            "duration_set_min": _number(duration_set_min),
            "duration_actual_s": round(duration_actual_s, 2),
        })
        info["stopped_early"] = bool(stopped_early)
        if assay_name == "Object Recognition":
            objects = [_drop_empty({"name": f"object {i + 1}", **o})
                       for i, o in enumerate(animal.get("objects", []))]
            if objects:
                info["objects"] = objects
        info["cameras"] = [_camera_entry(r, camera_settings, encoder) for r in arena_results]
        info["creature_capture"] = {
            "experiment": assay["name"],
            "gpu": encoder == "h264_nvenc",
        }
        json_path = base.with_suffix(".json")
        _write_atomic(json_path, lambda f: json.dump(info, f, indent=2, ensure_ascii=False))
        written.append(json_path)

        log_ok = append_master_log(master_log, row) and log_ok
    return written, log_ok


def _camera_entry(r, camera_settings: dict, encoder: str) -> dict:
    entry = {
        "label": camera_label(r.label, r.arena),
        "camera_position": r.slot_id,
        "camera_settings": _applied_settings(camera_settings.get(r.slot_id), encoder),
    }
    entry.update(_drop_empty({
        "video": r.video.name if r.video else None,
        "timestamps_csv": r.timestamps.name if r.timestamps else None,
        "fps_set": OUTPUT_FPS,
        "fps_measured": round(r.fps_measured, 3) if r.fps_measured else None,
        "width_px": OUTPUT_WIDTH,
        "height_px": OUTPUT_HEIGHT,
        "frames": r.frames,
        "verified_frames_in_file": r.verified_frames,
        "repeated_frames": r.repeated,
    }))
    entry["repeated_frame_indices"] = list(r.repeated_frames)  # from 0, like the MP4
    if r.error:
        entry["error"] = r.error
    return entry


def _write_atomic(path: Path, write) -> None:
    """Write to a temporary name, then rename, so a crash never leaves half a
    file. ``write`` is called with the open text file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _applied_settings(saved: dict | None, encoder: str) -> dict:
    """Every setting used for this camera in the trial, changed or not: the
    video encoder plus each camera control, with the built-in defaults filled
    in for any the user never saved. ``apply: false`` means the camera was left
    at its own value for that control."""
    return {"encoder": encoder, **effective_controls((saved or {}).get("controls"))}


def _write_rows(f, rows: list[dict], header: bool) -> None:
    w = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
    if header:
        w.writeheader()
    w.writerows(rows)


def _append_rows(path: Path, rows: list[dict]) -> None:
    if path.exists() and path.stat().st_size > 0:
        # utf-8-sig: still reads the log after Excel re-saved it with a byte-order mark.
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            # A log from an older version has other columns: rewrite it once with
            # the current ones so new rows line up (old rows get blanks).
            old = list(reader) if reader.fieldnames != LOG_COLUMNS else None
        if old is not None:
            _write_atomic(path, lambda f: _write_rows(f, old + rows, header=True))
            return
        with open(path, "a", newline="", encoding="utf-8") as f:
            _write_rows(f, rows, header=False)
    else:
        with open(path, "w", newline="", encoding="utf-8") as f:
            _write_rows(f, rows, header=True)


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
        with open(pending, newline="", encoding="utf-8-sig", errors="replace") as f:
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
