import argparse
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon

from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.store import ReviewStore
from desktop.config import read_settings, user_directory, load_model_settings
from desktop.window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data")
    parser.add_argument("--state")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--session", help="打开指定会话")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("EmpathyCopilot")
    app.setOrganizationName("EmpathyCopilot")
    app.setStyle("Fusion")
    assets = (Path(sys._MEIPASS) / "desktop-assets" if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parents[1] / ".scratch" / "desktop-assets")
    if (assets / "icon.png").exists():
        app.setWindowIcon(QIcon(str(assets / "icon.png")))
    settings, api_key = load_model_settings(read_settings())
    source = args.data or settings.get("data_path") or os.getenv("COPILOT_DATA_PATH")
    if not source and not getattr(sys, "frozen", False) and DEFAULT_SOURCE.exists():
        source = str(DEFAULT_SOURCE)
    provider = None
    if source:
        try:
            provider = ExcelProvider(Path(source))
            settings["data_path"] = source
        except Exception:
            if args.smoke_test:
                return 2
            QMessageBox.warning(None, "数据暂时不可用", "请在主窗口点击“选择 Excel”，重新打开业务工作簿。")
    try:
        store = ReviewStore(args.state or user_directory() / "reviews.sqlite3")
        window = MainWindow(provider, store, settings, api_key=api_key)
        if args.session:
            for index in range(window.sessions.count()):
                item = window.sessions.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == args.session:
                    window.sessions.setCurrentItem(item)
                    break
            else:
                raise ValueError('未找到指定会话')
    except Exception:
        if args.smoke_test:
            raise
        QMessageBox.critical(None, "无法启动", "无法读取本地记录或业务数据，请检查文件权限和工作簿格式。")
        return 1

    def handle_exception(kind, error, traceback):
        # The GUI must not silently swallow a failed slot, or show credentials.
        QMessageBox.warning(window, "操作未完成", "本次操作未完成。请检查输入和文件权限，刷新后重试；当前回复仍保留。")

    if not args.smoke_test:
        sys.excepthook = handle_exception
    window.show()
    if args.smoke_test or args.screenshot:
        def capture():
            if args.screenshot:
                window.grab().save(args.screenshot)
            if args.smoke_test:
                app.quit()
        QTimer.singleShot(1800, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
