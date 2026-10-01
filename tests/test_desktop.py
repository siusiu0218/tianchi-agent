"""Native UI workflows against temporary records, without live API calls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget, QPushButton, QLabel

from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.store import ReviewStore
from copilot.summary import digest
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
        if not w.draft.toPlainText():
            w.draft.setPlainText('测试回复')
        return ReviewDialog(w, w.result, w.original, w.draft.toPlainText(), w.source)

    def test_sidebar_drag_and_summary_icon_preserve_draft(self):
        w = self.window
        self.select('S00268')
        w.draft.setPlainText('布局切换保留的草稿')
        split = w.inbox_split
        split.moveSplitter(0, 1)
        QTest.qWait(120)
        self.assertEqual(split.sizes()[0], 0)
        self.assertTrue(split.handle(1).isVisible())
        split.moveSplitter(240, 1)
        QTest.qWait(120)
        self.assertGreaterEqual(split.sizes()[0], 210)
        width = split.sizes()[2]
        for _ in range(3):
            w.summary_toggle.click()
            QTest.qWait(300)
            self.assertTrue(w.summary_panel.isHidden())
            self.assertTrue(w.risk_badge.isVisible())
            w.summary_toggle.click()
            QTest.qWait(300)
            self.assertAlmostEqual(split.sizes()[2], width, delta=1)
        split.toggle_list()
        w.summary_toggle.click()
        w.resize(1120, 740)
        w.summary_toggle.click()
        QTest.qWait(300)
        self.assertEqual(split.sizes()[0], 0)
        split.toggle_list()
        self.assertGreaterEqual(split.sizes()[0], 210)
        self.select('S00001')
        self.select('S00268')
        self.assertEqual(w.draft.toPlainText(), '布局切换保留的草稿')

    def test_message_map_exact_jump_and_session_reset(self):
        w = self.window
        self.select('S00268')
        QTest.qWait(150)
        self.assertEqual(w.message_map.count(), len(w.chat.messages))

        for index in (0, 3, len(w.chat.messages) - 1):
            item = w.message_map.item(index)
            identity = item.data(Qt.ItemDataRole.UserRole)
            self.assertIn(identity, item.toolTip())
            w.message_map.locate(item)
            QTest.qWait(60)
            self.assertIs(w.chat._highlighted, w.chat.rows[index].bubble)
            bar = w.chat.verticalScrollBar()
            expected = min(bar.maximum(), max(0, w.chat.rows[index].y() - 16))
            self.assertAlmostEqual(bar.value(), expected, delta=2)
        self.assertFalse(w.chat.jump_to_message('missing-message'))
        old_id = w.chat.messages[0]['message_id']
        self.select('S00001')
        self.assertIsNone(w.chat._highlighted)
        self.assertFalse(w.chat.jump_to_message(old_id))
        self.assertEqual(w.message_map.count(), len(w.chat.messages))

    def test_keyboard_zoom_resizes_content_and_keeps_work(self):
        w = self.window
        self.select('S00268')
        w.draft.setPlainText('缩放后保留的草稿')
        original_row = w.sessions.sizeHintForRow(0)
        original_font = w.title.font().pixelSize()
        QTest.keyClick(w, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(w.zoom_percent, 110)
        self.assertGreater(w.sessions.sizeHintForRow(0), original_row)
        self.assertGreater(w.title.font().pixelSize(), original_font)
        self.assertEqual(w.draft.toPlainText(), '缩放后保留的草稿')
        self.assertEqual(w.sessions.currentItem().data(Qt.ItemDataRole.UserRole), 'S00268')
        QTest.keyClick(w, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(w.zoom_percent, 100)
        self.assertEqual(w.sessions.sizeHintForRow(0), original_row)
        w.set_zoom(130)
        w.adjust_zoom(1)
        self.assertEqual(w.zoom_percent, 130)
        QTest.keyClick(w, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.zoom_percent, 100)
        self.assertEqual(w.draft.toPlainText(), '缩放后保留的草稿')

    def test_sorting_preserves_selection_filters_and_draft(self):
        w = self.window
        self.select('S00268')
        w.draft.setPlainText('排序时不改变草稿')
        revision = w.draft_revision
        w.risk_filter.setCurrentIndex(w.risk_filter.findData('P0'))
        def visible_ids():
            return [w.sessions.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(w.sessions.count()) if not w.sessions.item(i).isHidden()]
        original = set(visible_ids())
        for mode in ('latest', 'oldest', 'risk', 'session'):
            w.set_session_sort(mode, mode)
            self.assertEqual(set(visible_ids()), original)
            self.assertEqual(w.sessions.currentItem().data(Qt.ItemDataRole.UserRole), 'S00268')
            self.assertEqual(w.draft_revision, revision)
            keys = [w.sessions.item(i).data(Qt.ItemDataRole.UserRole + 2) for i in range(w.sessions.count())]
            self.assertEqual(keys, sorted(keys, reverse=mode == 'latest'))
        self.assertEqual(w.draft.toPlainText(), '排序时不改变草稿')
        self.assertEqual(w.filter_button.text(), '')
        self.assertEqual(w.sort_button.text(), '')

    def test_summary_slide_has_intermediate_frames_and_reverses(self):
        w = self.window
        self.select('S00268')
        QTest.qWait(100)
        original = w.inbox_split.sizes()[2]
        w.summary_toggle.click()
        QTest.qWait(75)
        middle = w.inbox_split.sizes()[2]
        self.assertGreater(middle, 0)
        self.assertLess(middle, original)
        self.assertEqual(w.summary_panel.content.width(), original)
        w.summary_toggle.click()
        QTest.qWait(320)
        self.assertFalse(w.summary_panel.animating)
        self.assertFalse(w.summary_panel.isHidden())
        self.assertAlmostEqual(w.inbox_split.sizes()[2], original, delta=2)
        w.summary_toggle.click()
        QTest.qWait(320)
        self.assertTrue(w.summary_panel.isHidden())
        w.summary_toggle.click()
        QTest.qWait(320)
        self.assertEqual(w.inbox_split.sizes()[2], original)

    def test_recent_sort_single_action_toggles_direction(self):
        w = self.window
        self.select('S00268')
        w.draft.setPlainText('切换升降序时保留')
        action = w.sort_actions['recent']
        self.assertEqual(len(w.sort_button.menu().actions()), 3)
        self.assertEqual(w.sort_mode, 'latest')
        for expected, arrow in [('oldest', '↑'), ('latest', '↓'), ('oldest', '↑')]:
            action.trigger()
            self.assertEqual(w.sort_mode, expected)
            self.assertIn(arrow, action.text())
            self.assertTrue(action.isChecked())
            keys = [w.sessions.item(i).data(Qt.ItemDataRole.UserRole + 2) for i in range(w.sessions.count())]
            self.assertEqual(keys, sorted(keys, reverse=expected == 'latest'))
        w.sort_actions['risk'].trigger()
        action.trigger()
        self.assertEqual(w.sort_mode, 'latest')
        self.assertEqual(w.draft.toPlainText(), '切换升降序时保留')
        self.assertEqual(w.result['case']['session_id'], 'S00268')

    def test_layout_preserves_reading_anchor_and_risk_sources(self):
        w = self.window
        self.select('S00268')
        QTest.qWait(150)
        row = w.chat.rows[2]
        w.chat.stop_following()
        w.chat.verticalScrollBar().setValue(row.y())
        original = w.chat.verticalScrollBar().value()
        w.summary_toggle.click()
        QTest.qWait(300)
        w.summary_toggle.click()
        QTest.qWait(300)
        self.assertAlmostEqual(w.chat.verticalScrollBar().value(), original, delta=3)
        def inspect(dialog):
            from PySide6.QtWidgets import QTextBrowser
            content = dialog.findChild(QTextBrowser).toPlainText()
            self.assertIn('P0', content)
            for evidence in w.result['risk']['evidence']:
                self.assertIn(evidence['message_id'], content)
            return 0
        w.summary_toggle.click()
        with patch.object(QDialog, 'exec', inspect):
            w.risk_evidence.click()

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

    def test_inbox_filters_combine_reset_and_preserve_draft(self):
        w = self.window
        self.select('S00268')
        w.draft.setPlainText('筛选期间保留的草稿')
        w.risk_filter.setCurrentIndex(w.risk_filter.findData('P1'))
        self.assertTrue(w.sessions.currentItem().isHidden())
        self.assertEqual(w.result['case']['session_id'], 'S00268')
        self.assertEqual(w.draft.toPlainText(), '筛选期间保留的草稿')
        w.search.setText('S00001')
        w.image_filter.setCurrentIndex(w.image_filter.findData('image'))
        shown = [w.sessions.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(w.sessions.count()) if not w.sessions.item(i).isHidden()]
        self.assertEqual(shown, ['S00001'])
        w.image_filter.setCurrentIndex(w.image_filter.findData('text'))
        self.assertEqual(w.session_count.text(), '0')
        self.assertIn('没有符合条件', w.filter_notice.text())
        w.clear_session_filters()
        self.assertEqual(int(w.session_count.text()), w.sessions.count())
        self.assertEqual(w.draft.toPlainText(), '筛选期间保留的草稿')
        self.assertFalse(w.filter_notice.isVisible())
        w.risk_filter.setCurrentIndex(w.risk_filter.findData('待核实'))
        self.assertGreater(int(w.session_count.text()), 0)

    def test_inbox_report_filter_refreshes_after_status_changes(self):
        w = self.window
        w.report_filter.setCurrentIndex(w.report_filter.findData('pending'))
        self.assertEqual(w.session_count.text(), '0')
        self.select('S00001')
        w.reports.submit(token='filter-check', session='S00001', operator='验收',
                         reason='核对换货', messages=self.provider.messages('S00001')[:1],
                         risk=w.result['risk'])
        w.refresh_board()
        self.assertEqual(w.session_count.text(), '1')
        report = w.reports.reports()[0]
        w.reports.update(report, operator='验收', note='已核对', status='已处理')
        w.refresh_board()
        self.assertEqual(w.session_count.text(), '0')
        w.report_filter.setCurrentIndex(w.report_filter.findData('reported'))
        self.assertEqual(w.session_count.text(), '1')

    def test_business_snapshots_refresh_without_replacing_summary(self):
        self.select('S00268')
        folds = [button.text() for button in self.window.facts.findChildren(QPushButton, 'fold')]
        self.assertNotIn('▸  订单与物流', folds)
        self.assertNotIn('▾  订单与物流', folds)
        order_toggle = next(button for button in self.window.facts.findChildren(QPushButton, 'fold')
                            if '关联订单' in button.text())
        self.assertTrue(order_toggle.isChecked())
        self.assertTrue(order_toggle.parentWidget().layout().itemAt(1).widget().isVisible())
        pane = self.window.facts.handover
        before = pane.raw
        snapshot = [{'订单号': 'synthetic', '订单状态': '新快照状态'}]
        result = dict(self.window.result, case=dict(self.window.result['case'], orders=snapshot))
        self.window.facts.refresh_business(result, self.provider)
        self.app.processEvents()
        texts = [w.text() for w in self.window.facts.findChildren(QLabel)]
        self.assertIn('新快照状态', texts)
        self.assertIs(self.window.facts.handover, pane)
        self.assertEqual(pane.raw, before)

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
        self.assertEqual(self.window.task_list.count(), 0)  # Legacy reviews are not staff reports.
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
        with patch("desktop.window.generate_reply", return_value=output), patch.object(
                QMessageBox, "exec", return_value=QMessageBox.StandardButton.Ok):
            self.window.generate_model()
            self.assertTrue(self.window.sessions.isEnabled())
            self.window.worker.wait(3000)
            for _ in range(5):
                self.app.processEvents()
                QTest.qWait(10)
        self.assertEqual(self.window.draft.toPlainText(), '')
        self.assertIn('生成失败', self.window.source_label.text())
        self.assertTrue(self.window.sessions.isEnabled())
        empty = MainWindow(None, self.store, settings_directory=self.root)
        self.assertEqual(empty.sessions.count(), 0)
        self.assertFalse(empty.reply_button.isEnabled())
        empty.close()

    def test_summary_after_switch_does_not_reuse_deleted_worker(self):
        self.window.settings.update(base_url='http://localhost:9000/v1', model='test')
        self.window.api_key = 'test-key'
        self.select('S00268')
        with (patch('desktop.handover.generate_summary',
                    side_effect=lambda summary, config: dict(summary, source='模型概括 · 待人工核对')),
              patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Ok)):
            self.window.facts.handover.update_button.click()
            worker = self.window.summary_worker
            worker.wait(3000)
            self.app.processEvents()
        self.select('S00001')
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        errors = []
        try:
            with (patch.object(sys, 'excepthook', side_effect=lambda kind, error, trace: errors.append(str(error))),
                  patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Cancel)):
                self.window.facts.handover.update_button.click()
                self.app.processEvents()
        finally:
            self.window.summary_worker = None
        self.assertEqual(errors, [])

    def test_settings_do_not_persist_key(self):
        save_settings({"data_path": str(DEFAULT_SOURCE), "api_key": "never-save-this"}, self.root)
        self.assertNotIn("never-save-this", (self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(read_settings(self.root)["data_path"], str(DEFAULT_SOURCE))

    def test_composer_empty_restart_and_session_isolation(self):
        self.assertEqual(self.window.draft.toPlainText(), '')
        self.window.draft.setPlainText('客户 A 的未发送草稿')
        self.select('S00001')
        self.assertEqual(self.window.draft.toPlainText(), '')
        self.window.draft.setPlainText('客户 B 的未发送草稿')
        reopened = MainWindow(self.provider, ReviewStore(self.store.path), settings_directory=self.root)
        self.assertEqual(reopened.draft.toPlainText(), '客户 A 的未发送草稿')
        reopened.close()
        self.select('S00268')
        self.assertEqual(self.window.draft.toPlainText(), '客户 A 的未发送草稿')

    def test_send_click_audits_final_text_and_clears_only_on_success(self):
        for session in ('S00268', 'S00001'):
            self.select(session)
            self.window.original = 'AI 原稿'
            self.window.source = 'AI 建议'
            self.window.draft.setPlainText('客服修改后的正文')
            with patch.object(self.store, 'send_composed', side_effect=OSError):
                self.window.reply_button.click()
            self.assertEqual(self.window.draft.toPlainText(), '客服修改后的正文')
            self.window.reply_button.click()
            self.window.reply_button.click()
            self.assertEqual(self.window.draft.toPlainText(), '')
            self.assertEqual(len(self.store.simulated_messages(session)), 1)
            self.assertEqual(self.store.history(session)[0]['original'], 'AI 原稿')
            self.assertEqual(self.store.history(session)[0]['edited'], '客服修改后的正文')
            self.assertIn('客服修改后的正文', self.window.chat.toPlainText())
            self.assertIsNone(self.store.composer_draft(self.window.draft_scope(), session))

    def test_reports_are_explicit_persistent_and_independent_of_replies(self):
        from desktop.reporting import ReportDialog, HandleReportDialog, AllChatsDialog
        from copilot.reports import ReportStore
        self.window.draft.setPlainText('普通回复')
        self.window.reply_button.click()
        self.assertEqual(self.window.reports.reports(), [])
        self.assertEqual(self.store.tasks(), [])
        browser = AllChatsDialog(self.window)
        self.assertEqual(browser.sessions.count(), len(self.provider.sessions()))
        browser.sessions.setCurrentText('S00001')
        self.assertIn(self.provider.messages('S00001')[0]['message_text'], browser.chat.toPlainText())
        self.assertEqual(self.window.reports.reports(), [])
        browser.close()
        dialog = ReportDialog(self.window)
        dialog.submit()
        self.assertEqual(self.window.reports.reports(), [])
        dialog.selection.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.reason.setPlainText('需要主任核实')
        dialog.submit()
        dialog.submit()
        persisted = ReportStore(ReviewStore(self.store.path))
        reports = persisted.reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(json.loads(reports[0]['payload'])['messages']), 1)
        self.assertEqual(self.window.task_list.count(), 1)
        self.assertIn('1', self.window.board_nav.text())
        self.select('S00001')
        other = ReportDialog(self.window)
        self.assertTrue(all(other.selection.item(i).checkState() == Qt.CheckState.Unchecked
                            for i in range(other.selection.count())))
        other.close()
        handler = HandleReportDialog(self.window, reports[0])
        handler.status.setCurrentText('已处理')
        handler.note.setText('已核实并回复客服')
        handler.save()
        self.assertEqual(persisted.reports()[0]['status'], '已处理')
        self.assertEqual(self.window.task_list.count(), 0)
        self.assertNotIn('1', self.window.board_nav.text())
        with self.assertRaisesRegex(ValueError, '已被其他操作更新'):
            persisted.update(reports[0], operator='主任', note='过期操作', status='处理中')
        self.assertEqual(len(persisted.events(reports[0]['id'])), 2)
        self.window.status_filter.setCurrentText('全部')
        self.assertEqual(self.window.task_list.count(), 1)
        for text in [x.text() for x in self.window.facts.findChildren(QPushButton)]:
            self.assertNotIn('工单', text)

    def prepare_model_result(self):
        w = self.window
        w.model_context_session = w.result['case']['session_id']
        w.model_input = json.dumps(w.result['case'], sort_keys=True)
        w.model_revision = w.draft_revision
        w.model_draft = w.draft.toPlainText()
        w.model_messages = self.store.simulated_messages(w.model_context_session)
        w.model_summary_fingerprint = digest(w.facts.handover.reply_summary())
        return {'status': 'model', 'text': '新的 AI 回复', 'notice': '建议'}

    def test_reply_rejected_when_human_summary_changes_during_generation(self):
        pane = self.window.facts.handover
        pane.update_local()
        output = self.prepare_model_result()
        item = pane.displayed['items'][0]
        pane.ledger.correct(pane.session, item, '已核对的摘要修订', '测试员', '核对原文')
        self.window.model_completed(output)
        self.assertEqual(self.window.draft.toPlainText(), '')
        self.assertIn('未采用旧建议', self.window.statusBar().currentMessage())

    def test_ai_empty_fill_preview_cancel_and_accept(self):
        output = self.prepare_model_result()
        with patch.object(self.window, 'preview_suggestion') as preview:
            self.window.model_completed(output)
            preview.assert_not_called()
        self.assertEqual(self.window.draft.toPlainText(), output['text'])
        self.window.draft.setPlainText('客服已有文字')
        output = self.prepare_model_result()
        with patch.object(self.window, 'preview_suggestion', return_value=False):
            self.window.model_completed(output)
        self.assertEqual(self.window.draft.toPlainText(), '客服已有文字')
        with patch.object(self.window, 'preview_suggestion', return_value=True):
            self.window.model_completed(output)
        self.assertEqual(self.window.draft.toPlainText(), output['text'])

    def test_late_ai_never_overwrites_typing_other_session_or_sent_reply(self):
        output = self.prepare_model_result()
        self.window.draft.setPlainText('生成期间新输入')
        with patch.object(self.window, 'preview_suggestion', return_value=False) as preview:
            self.window.model_completed(output)
            preview.assert_called_once()
        self.assertEqual(self.window.draft.toPlainText(), '生成期间新输入')
        self.select('S00001')
        self.window.model_completed(output)
        self.assertEqual(self.window.draft.toPlainText(), '')
        self.select('S00268')
        output = self.prepare_model_result()
        self.window.reply_customer()
        self.window.model_completed(output)
        self.assertEqual(self.window.draft.toPlainText(), '')

    def test_failed_generation_keeps_existing_draft(self):
        self.window.draft.setPlainText('保留这段话')
        self.prepare_model_result()
        self.window.model_completed({'status': 'error', 'text': ''})
        self.assertEqual(self.window.draft.toPlainText(), '保留这段话')
        self.assertTrue(self.window.reply_button.isEnabled())

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
