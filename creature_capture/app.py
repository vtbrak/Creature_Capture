"""Application entry point and main window."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QProgressDialog, QTabWidget,
)

from creature_capture import APP_NAME, __version__, ffmpeg_util
from creature_capture.config import Settings, app_data_dir
from creature_capture.ui.common import CameraManager, EncoderProbe
from creature_capture.ui.record_tab import RecordTab
from creature_capture.ui.settings_tab import SettingsTab


def _windows_tuning() -> None:
    """1 ms timer resolution (accurate 20 fps clock) and higher priority."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
        ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                ABOVE_NORMAL_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.settings = settings
        self.cameras = CameraManager(settings)
        self.cameras.refresh_devices()
        self.encoder = EncoderProbe(settings)
        self.encoder.start()

        self.record = RecordTab(settings, self.cameras, self.encoder)
        self.settings_tab = SettingsTab(settings, self.cameras, self.encoder)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.record, "Record")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        self._record_dirty = False
        self.settings_tab.settings_changed.connect(self._mark_dirty)
        self.settings_tab.lock_changed.connect(self.record.set_locked)
        self.record.recording_changed.connect(self._recording_changed)
        self.statusBar().showMessage(f"Settings: {app_data_dir()}")
        self.resize(1400, 900)

    def _mark_dirty(self) -> None:
        self._record_dirty = True

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.record:
            self.settings_tab.deactivate()
            if self._record_dirty:
                self._record_dirty = False
                self.record.reload()
            else:
                self.record.activate()
        else:
            self.settings_tab.activate()

    def _recording_changed(self, on: bool) -> None:
        self.tabs.setTabEnabled(1, not on)
        self.settings_tab.set_recording(on)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.record.is_recording:
            QMessageBox.warning(self, "Recording in progress",
                                "Stop the recording (and wait for it to save) before closing.")
            event.ignore()
            return
        self.cameras.shutdown()
        event.accept()


def recover_unfinished(parent, settings: Settings) -> None:
    """Offer to repair videos left in crash-safe form by a crash/power loss."""
    files = ffmpeg_util.find_unfinished(Path(settings["base_path"]))
    if not files:
        return
    names = "\n".join(str(f) for f in files[:10]) + ("\n…" if len(files) > 10 else "")
    if QMessageBox.question(
        parent, "Recover interrupted recordings?",
        f"{len(files)} recording(s) were interrupted (crash or power loss) and are still in "
        f"crash-safe form:\n\n{names}\n\nConvert them to normal MP4 files now? "
        "Everything recorded up to the interruption is kept.",
    ) != QMessageBox.StandardButton.Yes:
        return
    prog = QProgressDialog("Recovering…", None, 0, len(files), parent)
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    failed = []
    for i, f in enumerate(files):
        prog.setValue(i)
        QApplication.processEvents()
        if ffmpeg_util.recover(f) is None:
            failed.append(f)
    prog.setValue(len(files))
    if failed:
        QMessageBox.warning(parent, "Recovery", "Could not convert:\n" + "\n".join(map(str, failed))
                            + "\n\nThese files can usually still be played as they are.")


def _excepthook(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        (app_data_dir() / "error.log").open("a", encoding="utf-8").write(text + "\n")
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc, tb)
    if QApplication.instance():
        QMessageBox.critical(None, "Unexpected error", text[-2000:])


def main() -> None:
    if "--self-test" in sys.argv:
        from creature_capture import selftest

        sys.exit(selftest.run())
    sys.excepthook = _excepthook
    _windows_tuning()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    settings = Settings.load()
    win = MainWindow(settings)
    win.show()
    recover_unfinished(win, settings)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
