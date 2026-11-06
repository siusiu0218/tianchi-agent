"""Customer-view simulations: state, persistence and isolation with fake models."""
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from copilot.reply_llm import reply_context
from desktop.simulation import SimulationWindow


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.contexts = []
        self.network_patch = patch('requests.sessions.Session.request', side_effect=AssertionError('No network'))
        self.network = self.network_patch.start()
        self.reply_patch = patch('desktop.simulation.generate_reply', side_effect=self.fake_reply)
        self.reply_mock = self.reply_patch.start()
        self.window = SimulationWindow(self.root, {'base_url': 'https://example.invalid/v1', 'model': 'test'}, 'fake')
        self.window.show()
        self.app.processEvents()

    def fake_reply(self, result, config, draft='', local_messages=(), summary=None):
        self.contexts.append(reply_context(result, draft, local_messages, summary))
        return {'status': 'model', 'text': '测试模型回复：收到您的反馈，我会协助核实。'}

    def wait_idle(self, window=None):
        window = window or self.window
        for _ in range(200):
            QTest.qWait(10)
            if not window.busy():
                return
        self.fail('Worker did not finish')

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.reply_patch.stop()
        self.network_patch.stop()
        self.assertEqual(self.network.call_count, 0)
        self.temp.cleanup()

    def customer(self, text, wait=True):
        self.window.customer_input.setPlainText(text)
        self.window.customer_send.click()
        if wait:
            self.wait_idle()

    def choose(self, sid):
        for i in range(self.window.sessions.count()):
            item = self.window.sessions.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == sid:
                self.window.sessions.setCurrentItem(item)
                return
        self.fail('Session not found')

    def test_multiturn_context_alignment_risk_and_restart(self):
        w = self.window
        self.customer('收到的瓶子破了，我要换货。')
        sid = w.session
        self.customer('我不换了，我要退款，而且用了之后脸红肿刺痛。')
        self.assertEqual(w.result['risk']['level'], 'P0')
        self.assertTrue(w.result['risk']['evidence'])
        self.assertEqual([m['角色'] for m in w.chat.messages], ['买家', '客服', '买家', '客服'])
        self.assertEqual([r.outgoing for r in w.chat.rows], [True, False, True, False])
        self.assertEqual(len(self.contexts[-1]['messages']), 3)
        self.assertEqual(self.contexts[-1]['messages'][-1]['role'], '买家')
        self.assertEqual(w.store.history(sid), [])  # No fabricated human approval.
        w.customer_input.setPlainText('还未发送的客户文字')
        w.close()
        restored = SimulationWindow(self.root)
        self.assertEqual(len(restored.provider.messages(sid)), 4)
        self.assertEqual(restored.customer_input.toPlainText(), '还未发送的客户文字')
        self.assertEqual(restored.result['case']['orders'], [])
        self.assertEqual(restored.result['case']['tickets'], [])
        restored.close()

    def test_blank_validation_and_customer_save_failure(self):
        w = self.window
        self.customer('   ')
        self.assertEqual(w.provider.sessions(), [])
        self.customer('字' * 4001)
        self.assertEqual(w.provider.sessions(), [])
        with patch.object(w.provider, 'append_customer', side_effect=OSError('disk')):
            self.customer('保存失败应保留')
        self.assertEqual(w.customer_input.toPlainText(), '保存失败应保留')
        self.assertEqual(self.reply_mock.call_count, 0)

    def test_send_blocked_while_reply_allows_typing_and_close_waits(self):
        w = self.window
        gate = threading.Event()
        def delayed(*args, **kwargs):
            gate.wait(2)
            return self.fake_reply(*args, **kwargs)
        try:
            self.reply_mock.side_effect = delayed
            self.customer('我要换货', wait=False)
            self.assertFalse(w.customer_send.isEnabled())
            w.customer_input.setPlainText('先打下一句')
            w.send_customer()
            w.generate_model()
            self.assertEqual(len(w.provider.messages(w.session)), 1)
            self.assertTrue(w.customer_input.isEnabled())
            self.assertFalse(w.close())
        finally:
            gate.set()
            self.wait_idle()
        self.assertEqual(w.customer_input.toPlainText(), '先打下一句')
        self.assertTrue(w.customer_send.isEnabled())
        self.assertEqual(len(w.provider.messages(w.session)), 2)

    def test_failure_retry_without_duplicate_customer_or_reply(self):
        w = self.window
        self.reply_mock.return_value = {'status': 'error', 'text': ''}
        self.reply_mock.side_effect = None
        self.customer('我要退款')
        self.assertEqual(len(w.chat.messages), 1)
        self.assertTrue(w.retry_button.isVisible())
        self.reply_mock.side_effect = self.fake_reply
        w.retry_button.click()
        self.wait_idle()
        w.generate_model()
        self.assertEqual(len(w.chat.messages), 2)
        self.assertEqual(self.reply_mock.call_count, 2)

    def test_reply_save_failure_and_idempotency(self):
        w = self.window
        with patch.object(w.provider, 'append_reply', side_effect=OSError('disk')):
            self.customer('我要换货')
        self.assertEqual(len(w.chat.messages), 1)
        expected = copy.deepcopy(w.provider.messages(w.session))
        w.retry_button.click()
        self.wait_idle()
        with self.assertRaises(ValueError):
            w.provider.append_reply(w.session, '重复回复', expected)
        self.assertEqual(len(w.provider.messages(w.session)), 2)

    def test_switch_discards_late_reply_and_restores_input(self):
        w = self.window
        gate = threading.Event()
        try:
            self.reply_mock.side_effect = lambda *a, **kw: (gate.wait(2), self.fake_reply(*a, **kw))[1]
            self.customer('第一段对话', wait=False)
            sid = w.session
            w.customer_input.setPlainText('保留下一句话')
            w.new_test()
            self.assertNotEqual(w.session, sid)
        finally:
            gate.set()
            self.wait_idle()
        self.assertEqual(len(w.provider.messages(sid)), 1)
        self.assertEqual(w.chat.messages, [])
        self.choose(sid)
        self.assertEqual(w.customer_input.toPlainText(), '保留下一句话')
        self.assertIn('旧回复未写入', w.test_notice.text())
        self.reply_mock.side_effect = self.fake_reply
        w.retry_button.click()
        self.wait_idle()
        self.assertEqual(len(w.chat.messages), 2)

    def test_external_change_rejects_stale_reply(self):
        w = self.window
        gate = threading.Event()
        try:
            self.reply_mock.side_effect = lambda *a, **kw: (gate.wait(2), self.fake_reply(*a, **kw))[1]
            self.customer('换货', wait=False)
            w.provider.append_customer(w.session, '现在改退款')
        finally:
            gate.set()
            self.wait_idle()
        self.assertEqual(len(w.provider.messages(w.session)), 2)
        self.assertIn('未采用旧回复', w.test_notice.text())

    def test_missing_config_preserves_customer_and_can_retry(self):
        w = self.window
        w.api_key = ''
        self.customer('没有配置时先保存')
        self.assertEqual(len(w.chat.messages), 1)
        self.assertIn('模型连接设置', w.test_notice.text())
        self.assertEqual(self.reply_mock.call_count, 0)
        w.api_key = 'fake'
        w.retry_button.click()
        self.wait_idle()
        self.assertEqual(len(w.chat.messages), 2)

    def test_summary_explicit_stale_does_not_block_reply_and_failure_keeps_old(self):
        w = self.window
        self.customer('瓶子破了，我要换货')
        pane = w.facts.handover
        self.assertFalse(pane.raw.get('source'))
        calls = []
        def summary(pending, config):
            calls.append(copy.deepcopy(pending))
            result = copy.deepcopy(pending)
            result['source'] = '测试模型摘要 · 待人工核对'
            return result
        with patch('desktop.handover.generate_summary', side_effect=summary):
            pane.update_button.click()
            self.assertFalse(w.customer_send.isEnabled())
            self.assertFalse(w.new_test_button.isEnabled())
            self.wait_idle()
        self.assertEqual(len(calls), 1)
        saved = copy.deepcopy(pane.raw)
        self.customer('不换了，我要退款')
        pane = w.facts.handover
        self.assertEqual(len(w.chat.messages), 4)
        self.assertIn('摘要待更新', pane.notice.text())
        self.assertNotIn('handover', self.contexts[-1])
        with patch('desktop.handover.generate_summary', side_effect=ValueError('测试摘要失败')):
            pane.update_button.click()
            self.wait_idle()
        self.assertEqual(pane.raw, saved)
        self.assertIn('旧摘要和人工纠正已保留', pane.notice.text())

    def test_unsent_blank_input_survives_new_and_restart(self):
        w = self.window
        sid = w.session
        w.customer_input.setPlainText('尚未发出的第一句')
        w.new_test()
        self.choose(sid)
        self.assertEqual(w.customer_input.toPlainText(), '尚未发出的第一句')
        self.assertIsNone(w.result)
        w.close()
        restored = SimulationWindow(self.root)
        self.assertEqual(restored.customer_input.toPlainText(), '尚未发出的第一句')
        self.assertIsNone(restored.result)
        restored.close()

    def test_summary_late_response_is_not_saved(self):
        w = self.window
        self.customer('收到的瓶子破了')
        pane = w.facts.handover
        gate = threading.Event()
        def delayed(pending, config):
            gate.wait(2)
            return dict(pending, source='测试模型摘要')
        with patch('desktop.handover.generate_summary', side_effect=delayed):
            try:
                pane.update_button.click()
                w.provider.append_customer(w.session, '现在补充了新信息')
            finally:
                gate.set()
                self.wait_idle()
        self.assertFalse(pane.raw.get('source'))
        self.assertIn('未采用旧结果', pane.notice.text())

    def test_long_plain_text_and_keyboard_send(self):
        w = self.window
        w.customer_input.setFocus()
        text = '<b>纯文本</b>\n' + '这是客户提供的长消息。' * 50
        w.customer_input.setPlainText(text)
        QTest.keyClick(w.customer_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.wait_idle()
        w.resize(1040, 640)
        QTest.qWait(100)
        self.assertEqual(w.chat.messages[0]['message_text'], text)
        row = w.chat.rows[0]
        self.assertEqual(row.body.textFormat(), Qt.TextFormat.PlainText)
        self.assertGreaterEqual(row.body.height(), row.body.heightForWidth(row.body.width()))
        self.assertLess(row.bubble.width(), w.chat.viewport().width())

    def test_main_entry_menu_and_state_isolation(self):
        from desktop.window import MainWindow
        from copilot.store import ReviewStore
        main = MainWindow(None, ReviewStore(self.root / 'normal.sqlite3'), settings_directory=self.root)
        main.show()
        main.settings_nav.click()
        self.app.processEvents()
        self.assertTrue(main.settings_menu.isVisible())
        main.settings_menu.hide()
        main.simulation_action.trigger()
        test = main.simulation_window
        test.customer_input.setPlainText('独立的测试消息')
        test.customer_send.click()
        self.assertNotEqual(test.store.path, main.store.path)
        self.assertEqual(main.store.simulated_messages(test.session), [])
        self.assertFalse(main.menuBar().actions())
        main.open_simulation()
        self.assertIs(main.simulation_window, test)
        test.close()
        main.close()


if __name__ == '__main__':
    unittest.main()
