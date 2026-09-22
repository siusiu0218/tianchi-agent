"""Render the real widgets with isolated preview records; never touch user records."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from copilot.data import ExcelProvider
from copilot.store import ReviewStore
from desktop.window import MainWindow, ReviewDialog, TaskDialog


def capture(widget, filename):
    widget.show()
    QApplication.processEvents()
    QTest.qWait(250)
    widget.grab().save(str(output / filename))


app = QApplication([])
app.setStyle("Fusion")
output = Path(__file__).resolve().parents[1] / ".scratch" / "desktop-redesign"
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    store = ReviewStore(Path(directory) / "preview.sqlite3")
    window = MainWindow(ExcelProvider(), store, settings_directory=Path(directory))
    capture(window, "inbox-p0.png")
    window.sessions.setCurrentRow(1)
    capture(window, "inbox-service.png")
    window.resize(1120, 740)
    capture(window, "inbox-compact.png")
    window.resize(1440, 900)
    dialog = ReviewDialog(window, window.result, window.original, window.draft.toPlainText(), window.source)
    capture(dialog, "review.png")
    dialog.close()
    for row in (0, 1):
        window.sessions.setCurrentRow(row)
        case = window.result["case"]
        store.save(session=case["session_id"], cutoff=case["cutoff"], original=window.original,
                   edited=window.original, source="本地模板", risk=window.result["risk"],
                   decision="采纳", operator="预览测试", owner="预览负责人", reason="仅供界面验证", confirmed=True)
    window.tabs.setCurrentIndex(1)
    capture(window, "board.png")
    dialog = TaskDialog(window, store.tasks()[0])
    capture(dialog, "task.png")
    dialog.close()
    window.close()
print(output)
