import argparse
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt

from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.store import ReviewStore
from desktop.config import read_settings, user_directory, load_model_settings
from desktop.window import MainWindow
from desktop.icons import svg_icon


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data")
    parser.add_argument("--state")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--session", help="打开指定会话")
    parser.add_argument("--reporting-check", help="隔离数据库中运行上报验收，输出截图目录")
    parser.add_argument("--summary-rejection-check", help="隔离数据库中验证失败摘要提示，输出截图目录")
    args = parser.parse_args()
    check_temp = tempfile.TemporaryDirectory() if args.reporting_check or args.summary_rejection_check else None
    if check_temp:
        args.state = str(Path(check_temp.name) / "check.sqlite3")
        args.smoke_test = True
    app = QApplication(sys.argv[:1])
    app.setApplicationName("EmpathyCopilot")
    app.setOrganizationName("EmpathyCopilot")
    app.setStyle("Fusion")
    app.setWindowIcon(svg_icon("messages-square", "#ffffff", brand=True))
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
            if args.reporting_check:
                try:
                    from desktop.reporting_check import check
                    check(window, args.reporting_check)
                except Exception:
                    import traceback
                    destination = Path(args.reporting_check)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
                    app.exit(1)
                    return
            if args.summary_rejection_check:
                try:
                    from desktop.summary_rejection_check import check
                    check(window, args.summary_rejection_check)
                except Exception:
                    import traceback
                    destination = Path(args.summary_rejection_check)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
                    app.exit(1)
                    return
            if args.screenshot:
                window.grab().save(args.screenshot)
            if args.smoke_test:
                app.quit()
        QTimer.singleShot(1800, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
