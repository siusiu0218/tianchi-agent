"""Native UI workflows against temporary records, without live API calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget, QPushButton

from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.store import ReviewStore
from desktop.config import read_settings, save_settings
from desktop.window import MainWindow, ReplyDialog, ReviewDialog, TaskDialog


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.provider = ExcelProvider(DEFAULT_SOURCE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ReviewStore(self.root / "reviews.sqlite3")
        self.window = MainWindow(self.provider, self.store, settings_directory=self.root)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.wait(3000)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def select(self, session):
        for i in range(self.window.sessions.count()):
            item = self.window.sessions.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == session:
                self.window.sessions.setCurrentItem(item)
                self.app.processEvents()
                QTest.qWait(100)
                return
        self.fail("Missing session " + session)

    def review_dialog(self):
        w = self.window
        return ReviewDialog(w, w.result, w.original, w.draft.toPlainText(), w.source)

    def fill_review(self, dialog):
        dialog.operator.setText("测试审核员")
        dialog.owner.setText("测试负责人")
        dialog.reason.setText("已核对原文")
        dialog.confirm.setChecked(True)

    def test_complete_history_search_and_draft_switch(self):
        self.select("S00268")
        self.assertEqual(self.window.result["risk"]["level"], "P0")
        for msg in self.provider.messages("S00268"):
            self.assertIn(msg["message_text"], self.window.chat.toPlainText())
        bar = self.window.chat.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())
        self.window.draft.setPlainText("暂存修改")
        self.select("S00001")
        self.assertIsNotNone(self.window.result["service"])
        self.assertNotEqual(self.window.draft.toPlainText(), "暂存修改")
        self.select("S00268")
        self.assertEqual(self.window.draft.toPlainText(), "暂存修改")
        self.window.search.setText("S00268")
        visible = [self.window.sessions.item(i) for i in range(self.window.sessions.count())
                   if not self.window.sessions.item(i).isHidden()]
        self.assertEqual(len(visible), 1)

    def test_review_restart_task_transitions_and_stale_rejection(self):
        dialog = self.review_dialog()
        dialog.save()
        self.assertEqual(self.store.history("S00268"), [])
        self.fill_review(dialog)
        dialog.save()
        dialog.save()
        persisted = ReviewStore(self.root / "reviews.sqlite3")
        self.assertEqual(len(persisted.history("S00268")), 1)
        self.window.refresh_board()
        self.assertEqual(self.window.task_list.count(), 1)
        task = persisted.tasks()[0]
        first, stale = TaskDialog(self.window, task), TaskDialog(self.window, task)
        for form in (first, stale):
            form.status.setCurrentText("处理中")
            form.actor.setText("测试主管")
            form.reason.setText("已分派处理")
            form.confirm.setChecked(True)
        first.save()
        stale.save()
        self.assertIn("已被其他操作更新", stale.error.text())
        self.assertEqual(persisted.task("S00268")["status"], "处理中")
        for target in ("已解决", "已关闭"):
            form = TaskDialog(self.window, persisted.tasks()[0])
            form.status.setCurrentText(target)
            form.actor.setText("测试主管")
            form.reason.setText("已完成核实")
            form.confirm.setChecked(True)
            form.save()
        self.assertEqual(persisted.task("S00268")["status"], "已关闭")
        self.assertEqual(len(persisted.events("S00268")), 4)

    def test_confirmation_not_carried_between_cases(self):
        dialog = self.review_dialog()
        self.fill_review(dialog)
        dialog.reason.setText("补充说明")
        self.assertFalse(dialog.confirm.isChecked())
        self.select("S00001")
        next_dialog = self.review_dialog()
        self.assertFalse(next_dialog.confirm.isChecked())
        self.assertEqual(next_dialog.owner.text(), "")
        self.assertEqual(next_dialog.reason.text(), "")

    def test_modified_and_rejected_reviews(self):
        self.window.draft.setPlainText("人工修改后的回复")
        dialog = self.review_dialog()
        self.assertEqual(dialog.decision.currentText(), "修改后确认")
        self.fill_review(dialog)
        dialog.save()
        self.assertEqual(self.store.history("S00268")[0]["edited"], "人工修改后的回复")
        self.select("S00001")
        rejection = self.review_dialog()
        self.fill_review(rejection)
        rejection.decision.setCurrentText("驳回")
        rejection.confirm.setChecked(True)
        rejection.save()
        self.assertIsNone(self.store.task("S00001"))

    def test_reply_button_records_only_reviewed_local_message(self):
        self.select("S00268")
        self.assertFalse(self.window.reply_button.isEnabled())
        review = self.review_dialog()
        self.fill_review(review)
        review.save()
        self.window.reply_button.setEnabled(True)
        dialog = ReplyDialog(self.window, "S00268", self.store.history("S00268")[0]["edited"])
        dialog.send()
        self.assertEqual(self.store.simulated_messages("S00268"), [])
        dialog.operator.setText("测试客服")
        dialog.confirm.setChecked(True)
        dialog.send()
        dialog.send()
        messages = self.store.simulated_messages("S00268")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["operator"], "测试客服")
        self.assertIn("本地模拟回复", self.window.simulated_chat_messages("S00268")[0]["message_text"])

    def test_background_model_fallback_and_empty_startup(self):
        self.window.settings.update(base_url="http://localhost:9000/v1", model="test")
        output = {"text": self.window.result["draft"], "status": "fallback", "notice": "测试回退"}
        with patch("desktop.window.generate_draft", return_value=output), patch.object(
                QMessageBox, "exec", return_value=QMessageBox.StandardButton.Ok):
            self.window.generate_model()
            self.assertFalse(self.window.sessions.isEnabled())
            self.window.worker.wait(3000)
            for _ in range(5):
                self.app.processEvents()
                QTest.qWait(10)
        self.assertEqual(self.window.source, "回退模板")
        self.assertTrue(self.window.sessions.isEnabled())
        empty = MainWindow(None, self.store, settings_directory=self.root)
        self.assertEqual(empty.sessions.count(), 0)
        self.assertFalse(empty.review_button.isEnabled())
        empty.close()

    def test_settings_do_not_persist_key(self):
        save_settings({"data_path": str(DEFAULT_SOURCE), "api_key": "never-save-this"}, self.root)
        self.assertNotIn("never-save-this", (self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(read_settings(self.root)["data_path"], str(DEFAULT_SOURCE))

    def test_session_clicks_never_show_detached_windows(self):
        class WindowWatcher(QObject):
            def __init__(self):
                super().__init__()
                self.unexpected = []

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                    self.unexpected.append(type(obj).__name__)
                return False

        watcher = WindowWatcher()
        self.app.installEventFilter(watcher)
        try:
            for row in [1, 0, 2, 1, 0] * 4:
                item = self.window.sessions.item(row)
                QTest.mouseClick(self.window.sessions.viewport(), Qt.MouseButton.LeftButton,
                                 pos=self.window.sessions.visualItemRect(item).center())
                self.app.processEvents()
                for toggle in self.window.facts.findChildren(QPushButton, "fold"):
                    toggle.click()
                    toggle.click()
            self.assertEqual(watcher.unexpected, [], "Switching sessions must never show a detached native window")
        finally:
            self.app.removeEventFilter(watcher)

    def test_bubbles_fit_narrow_window_and_keep_role_alignment(self):
        self.select("S00001")
        self.window.resize(1120, 740)
        QTest.qWait(200)
        feed = self.window.chat
        self.assertEqual(len(feed.rows), len(self.provider.messages("S00001")))
        for row in feed.rows:
            self.assertLessEqual(row.bubble.width(), row.width() - row.avatar.width())
            self.assertGreaterEqual(row.body.height(), row.body.heightForWidth(row.body.width()))
            if row.outgoing:
                self.assertLess(row.bubble.x(), row.avatar.x())
                self.assertGreater(row.bubble.x(), 0)
            else:
                self.assertGreater(row.bubble.x(), row.avatar.x())
        bar = feed.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())
        bar.setValue(0)
        QTest.qWait(100)
        self.assertEqual(bar.value(), 0)

    def test_sidebar_navigation_and_empty_board(self):
        QTest.mouseClick(self.window.board_nav, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertTrue(self.window.empty_tasks.isVisible())
        self.assertFalse(self.window.task_action.isEnabled())
        QTest.mouseClick(self.window.inbox_nav, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertTrue(self.window.inbox_nav.isChecked())

    def test_message_text_is_literal_and_multiline_is_not_clipped(self):
        from desktop.widgets import ChatFeed
        feed = ChatFeed()
        feed.resize(420, 450)
        feed.show()
        message = {"角色": "买家", "发送时间": "2026-09-17 12:00:00", "内容类型": "文字", "image_path": "",
                   "message_text": "<b>原文不是 HTML</b>\n" + "一段需要完整显示的很长的客户描述。" * 12}
        feed.set_messages([message])
        QTest.qWait(150)
        self.assertEqual(feed.rows[0].body.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(feed.toPlainText(), message["message_text"])
        body = feed.rows[0].body
        self.assertGreaterEqual(body.height(), body.heightForWidth(body.width()))
        feed.close()


if __name__ == "__main__":
    unittest.main()
