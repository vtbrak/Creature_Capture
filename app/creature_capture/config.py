"""Persistent application settings.

Settings live in the user's application-data folder (not next to the .exe),
so they survive downloading a new build:

* Windows: %APPDATA%\\CreatureCapture\\settings.json
* macOS:   ~/Library/Application Support/CreatureCapture/settings.json
* Linux:   ~/.config/CreatureCapture/settings.json

Set the CREATURE_CAPTURE_HOME environment variable to override (used by tests).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 2  # 2: Open Field gained a 90 min length

# Fixed recording format (per spec). Stored in settings for visibility but the
# UI does not expose them for editing.
OUTPUT_FPS = 20
OUTPUT_WIDTH = 800
OUTPUT_HEIGHT = 600


def app_data_dir() -> Path:
    override = os.environ.get("CREATURE_CAPTURE_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "CreatureCapture"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "CreatureCapture"
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "CreatureCapture"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def animals_path() -> Path:
    return app_data_dir() / "animals.csv"


def default_base_path() -> str:
    if sys.platform == "win32":
        if Path("D:/").exists():
            return "D:\\BehaviorVideos"
        return "C:\\BehaviorVideos"
    return str(Path.home() / "BehaviorVideos")


# Assay names from the Track Tamer metadata standard (docs/metadata_standard.md,
# section 3), each with its fixed lists of variants and phases. The info
# JSON's "assay" must be exactly one of these names for Track Tamer to set the
# test type; "assay_variant" and "phase" come from that assay's lists.
# "sessions": the assay normally has more than one session per trial day, so
# the Record tab asks for the session as well as the trial day.
STANDARD_ASSAYS: dict[str, dict] = {
    "Elevated Plus Maze": {"variants": [], "phases": []},
    "Open Field": {"variants": [], "phases": []},
    "Object Recognition": {"variants": ["Novel Object Recognition", "Spatial Object Recognition"],
                           "phases": ["Habituation", "Training", "Test"]},
    "Acoustic Startle Response": {"variants": ["Prepulse Inhibition", "Startle Habituation"],
                                  "phases": []},
    "Conditioned Place Preference": {"variants": [],
                                     "phases": ["Pretest", "Conditioning", "Test"]},
    "Puzzle Box": {"variants": [], "phases": [], "sessions": True},
}
# Only the assays recorded with this app are offered. The standard also lists
# Skilled Reaching, which is recorded with another app (Pellet Paparazzi).
OBJECT_KINDS = ["Familiar", "Novel", "Moved"]


def assay_variants(std: str) -> list[str]:
    return STANDARD_ASSAYS.get(std, {}).get("variants", [])


def assay_phases(std: str) -> list[str]:
    return STANDARD_ASSAYS.get(std, {}).get("phases", [])


# Older experiment names that map to a standard assay.
_ASSAY_ALIASES = {"elevated plus": "Elevated Plus Maze", "epm": "Elevated Plus Maze"}


def standard_assay(assay: dict) -> str:
    """The standard assay name for an experiment, or "" if it isn't one of
    them (then the experiment's own name is written and Track Tamer asks).
    An experiment with no assay type set is matched by its name, which also
    picks up assays added to the list after the experiment was saved."""
    if assay.get("standard_assay"):
        return assay["standard_assay"]
    name = assay.get("name", "").strip().lower()
    for std in STANDARD_ASSAYS:
        if std.lower() == name:
            return std
    return _ASSAY_ALIASES.get(name, "")


def sessions_default(std: str) -> bool:
    return bool(STANDARD_ASSAYS.get(std, {}).get("sessions", False))


def has_sessions(assay: dict) -> bool:
    """Does this experiment run more than one session per trial day? The
    experiment's own setting if it has one, else its assay type's default."""
    if "multiple_sessions" in assay:
        return bool(assay["multiple_sessions"])
    return sessions_default(standard_assay(assay))


DEFAULT_SLOTS = [
    {"id": "Arena1_Overhead", "name": "Arena 1 Overhead", "device": None},
    {"id": "Arena1_Horizontal", "name": "Arena 1 Horizontal", "device": None},
    {"id": "Arena2_Overhead", "name": "Arena 2 Overhead", "device": None},
    {"id": "Arena2_Horizontal", "name": "Arena 2 Horizontal", "device": None},
    {"id": "Camera5", "name": "Camera 5 (EPM / Puzzle Box)", "device": None},
]

DEFAULT_ASSAYS = [
    {
        "name": "Open Field",
        "standard_assay": "Open Field",
        "folder": "OpenField",
        "durations": [5, 10, 15, 20, 30, 60, 90],
        "default_duration": 10,
        "arenas": [
            {
                "name": "Arena1",
                "cameras": [
                    {"slot": "Arena1_Overhead", "label": "Arena1_Overhead"},
                    {"slot": "Arena1_Horizontal", "label": "Arena1_Horizontal"},
                ],
            },
            {
                "name": "Arena2",
                "cameras": [
                    {"slot": "Arena2_Overhead", "label": "Arena2_Overhead"},
                    {"slot": "Arena2_Horizontal", "label": "Arena2_Horizontal"},
                ],
            },
        ],
    },
    {
        "name": "Elevated Plus",
        "standard_assay": "Elevated Plus Maze",
        "folder": "ElevatedPlus",
        "durations": [5, 10, 15],
        "default_duration": 5,
        "arenas": [
            {"name": "EPM", "cameras": [{"slot": "Camera5", "label": "Overhead"}]},
        ],
    },
    {
        "name": "Puzzle Box",
        "standard_assay": "Puzzle Box",
        "folder": "PuzzleBox",
        "durations": [5, 10, 15, 20, 30],
        "default_duration": 10,
        "arenas": [
            {"name": "PuzzleBox", "cameras": [{"slot": "Camera5", "label": "Overhead"}]},
        ],
    },
]

DEFAULTS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    "base_path": None,  # filled in lazily with default_base_path()
    "date_subfolders": True,
    "locked": False,
    # Rate requested from the camera. Capturing faster than 20 fps (e.g. 30)
    # guarantees a fresh frame is available at every 20 fps output tick, so
    # repeated frames only happen when a camera genuinely drops frames.
    "camera_capture_fps": 30,
    # Encoder quality: lower = better quality / bigger files. ~18-23 is sensible.
    "quality": 20,
    "encoder": "auto",  # auto | h264_nvenc | libx264
    "overlay": {
        "enabled": True,
        "font_scale": 0.5,
        "show_elapsed": True,
        "show_frame": True,
        "show_fps": True,
        "mark_repeats": True,
    },
    "disk_warning_gb": 20,
    "simulated_cameras": 0,  # test-pattern cameras for development without hardware
    "slots": DEFAULT_SLOTS,
    "assays": DEFAULT_ASSAYS,
    # camera_settings[assay_name][slot_id] = {"enabled": bool, "controls": {...}}
    "camera_settings": {},
    "last_assay": "Open Field",
    "last_experimenter": "",
    "last_cohort": "",
}


def _merge_defaults(data: dict, defaults: dict) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("camera_settings",):
            out[k] = _merge_defaults(v, out[k])
        else:
            out[k] = v
    return out


def _migrate(data: dict) -> None:
    """Bring a settings file saved by an older version up to date, in place.
    (Saved experiments replace the built-in ones, so new defaults don't reach
    them by themselves.)"""
    if data.get("version", 1) < 2:
        for a in data.get("assays", []):
            if standard_assay(a) == "Open Field" and 90 not in a.get("durations", []):
                a["durations"] = sorted([*a.get("durations", []), 90])
    data["version"] = SETTINGS_VERSION


class Settings:
    """Thin wrapper around a JSON dict with convenience accessors."""

    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.path = path or settings_path()
        self._set_data(data or {})

    def _set_data(self, data: dict) -> None:
        _migrate(data)
        self.data = _merge_defaults(data, DEFAULTS)
        if not self.data.get("base_path"):
            self.data["base_path"] = default_base_path()

    # ----------------------------------------------------------------- io
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or settings_path()
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # Keep a copy of the unreadable file rather than silently losing it.
                try:
                    path.replace(path.with_suffix(".corrupt.json"))
                except OSError:
                    pass
                data = {}
        return cls(data, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix="settings.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def export_to(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def import_from(self, path: Path) -> None:
        self._set_data(json.loads(Path(path).read_text(encoding="utf-8")))
        self.save()

    # ------------------------------------------------------------ helpers
    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def assays(self) -> list[dict]:
        return self.data["assays"]

    @property
    def slots(self) -> list[dict]:
        return self.data["slots"]

    def assay(self, name: str) -> dict | None:
        for a in self.assays:
            if a["name"] == name:
                return a
        return None

    def slot(self, slot_id: str) -> dict | None:
        for s in self.slots:
            if s["id"] == slot_id:
                return s
        return None

    def camera_settings(self, assay_name: str, slot_id: str) -> dict:
        """Per-assay, per-camera settings (created on first access)."""
        by_assay = self.data["camera_settings"].setdefault(assay_name, {})
        cs = by_assay.setdefault(slot_id, {})
        cs.setdefault("enabled", True)
        cs.setdefault("controls", {})
        return cs
