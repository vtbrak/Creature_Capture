"""Keep test files on the project's own drive, and remove them after every run.

Each run gets its own folder, tests/.tmp/run-<time>-<process>, used for pytest's
tmp_path and for anything made with Python's tempfile module. The folder is
removed when the run ends, pass or fail. Folders left by a run that was killed
are removed by a later run once they are over 6 hours old. tests/.tmp/ is in
.gitignore.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
STALE_AFTER_S = 6 * 3600

_run_dir: Path | None = None


def _remove_stale_runs() -> None:
    now = time.time()
    for old in TMP_ROOT.glob("run-*"):
        try:
            if now - old.stat().st_mtime > STALE_AFTER_S:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def pytest_configure(config):
    global _run_dir
    TMP_ROOT.mkdir(exist_ok=True)
    _remove_stale_runs()
    _run_dir = TMP_ROOT / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    _run_dir.mkdir()
    if config.option.basetemp is None:
        config.option.basetemp = str(_run_dir / "pytest")
    tempfile.tempdir = str(_run_dir)


def pytest_unconfigure(config):
    tempfile.tempdir = None
    if _run_dir is not None:
        shutil.rmtree(_run_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _program_folder_elsewhere(tmp_path_factory, monkeypatch):
    """Test folders sit inside this source copy (tests/.tmp), which the app would
    rightly warn about as a video folder. Tests run as if the program were in a
    folder of its own, and only a CreatureCapture.exe marks another copy."""
    from creature_capture import config

    here = tmp_path_factory.mktemp("program")
    monkeypatch.setattr(config, "program_folder", lambda: here)
    monkeypatch.setattr(config, "_is_program_folder",
                        lambda folder: (folder / "CreatureCapture.exe").is_file())
