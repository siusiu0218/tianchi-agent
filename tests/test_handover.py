import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PySide6.QtWidgets import QApplication

from copilot.data import ExcelProvider
from copilot.summary import candidates, FIELDS
from copilot.summary_store import SummaryStore
from desktop.handover import HandoverPane, CorrectionDialog, LinkDialog, emphasize


class HandoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.original = ExcelProvider()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = copy.deepcopy(self.original)
        self.provider.source = Path(self.temp.name) / 'synthetic.xlsx'
        self.provider.source.touch()
        self.path = Path(self.temp.name) / 'state.sqlite3'
        self.pane = HandoverPane(self.provider, self.path, 'S00001')
        self.pane.show()

    def tearDown(self):
        self.pane.close()
        self.pane.deleteLater()
        self.app.processEvents()

    def add_message(self, text, session='S00001'):
        frame = self.provider.frames['聊天记录']
        row = frame.loc[frame['会话ID'].eq('S00001')].iloc[0].copy()
        row['会话ID'], row['message_id'] = session, 'synthetic-new-' + str(len(frame))
        row['发送时间'], row['message_text'], row['角色'] = '2026-06-01 10:00:00', text, '买家'
        self.provider.frames['聊天记录'] = pd.concat([frame, row.to_frame().T], ignore_index=True)

    def test_correction_ui_restart_update_and_conflict(self):
        item = next(i for i in self.pane.displayed['items'] if i['field'] == '诉求' and i['topic'] == '商品与换货')
        dialog = CorrectionDialog(self.pane, item)
        dialog.editor.setPlainText('人工核实：希望换货')
        dialog.save()
        self.assertIn('请填写', dialog.error.text())
        dialog.actor.setText('测试员')
        dialog.reason.setText('已核对原文')
        dialog.save()
        self.assertTrue(any(i.get('correction') for i in self.pane.displayed['items']))
        reopened = HandoverPane(self.provider, self.path, 'S00001')
        self.assertTrue(any(i['text'] == '人工核实：希望换货' for i in reopened.displayed['items']))
        reopened.close()
        reopened.deleteLater()
        old = self.pane.raw['fingerprint']
        self.add_message('换货还没收到，我现在想改退款')
        self.pane.refresh_pending()
        self.assertEqual(old, self.pane.raw['fingerprint'])
        self.assertTrue(self.pane.update_button.isEnabled())
        result = self.pane.generate()
        result['source'] = '模型概括 · 待人工核对'
        self.pane.model_ready(result)
        corrected = next(i for i in self.pane.displayed['items'] if i['id'] == item['id'])
        self.assertEqual(corrected['text'], '人工核实：希望换货')
        self.assertTrue(corrected['conflict'])
        self.assertTrue(self.pane.changed)

    def test_failed_update_keeps_prior_version(self):
        old = copy.deepcopy(self.pane.raw)
        result = self.pane.generate()
        result['source'] = '模型概括 · 待人工核对'
        with patch.object(self.pane.ledger, 'save', side_effect=OSError('test')):
            self.pane.model_ready(result)
        self.assertEqual(old, self.pane.raw)
        self.assertEqual(old, self.pane.ledger.latest('S00001'))
        self.assertIn('失败', self.pane.notice.text())

    def test_compact_preview_preserves_full_text_and_stays_saved_until_update(self):
        result = self.pane.generate()
        result['source'] = '测试摘要 · 待人工核对'
        for item in result['items']:
            item['authored'] = True
            if item['field'] == '经过概述':
                item['text'] = '消费者报告商品破损。客服称已登记换货，消费者等待收货。'
        self.pane.model_ready(result)
        self.app.processEvents()
        self.assertTrue(self.pane.full_summary.isHidden())
        self.assertIn('未提供姓名', self.pane.consumer_label.text())
        self.assertLessEqual(len(self.pane.overview.lines), 3)
        self.pane.full_toggle.click()
        self.assertFalse(self.pane.full_summary.isHidden())
        self.assertIn('消费者报告商品破损', self.pane.field_labels['经过概述'].text())
        old_lines = self.pane.overview.lines[:]
        self.add_message('现在不换货了，我想退款')
        self.pane.refresh_pending()
        self.assertEqual(old_lines, self.pane.overview.lines)
        self.assertIn('摘要待更新', self.pane.notice.text())

    def test_emphasis_escapes_markup_and_preserves_risk_negation(self):
        rendered = emphasize('<img src=x>消费者尚未就医，要求退款。', True)
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;img', rendered)
        self.assertIn('消费者尚未就医</b>', rendered)
        self.assertIn('<b>退款</b>', rendered)
        self.assertNotIn('color:', emphasize('已换货，待回访。'))

    def test_primary_action_uses_model_for_initial_generation_and_updates(self):
        with patch.object(self.pane, 'generate_model') as generate_model:
            self.pane.update_button.click()
            generate_model.assert_called_once_with()

            result = self.pane.generate()
            result['source'] = '模型概括 · 待人工核对'
            self.pane.model_ready(result)
            self.add_message('换货还没收到，现在改为退款')
            self.pane.refresh_pending()
            self.pane.update_button.click()

        self.assertEqual(generate_model.call_count, 2)

    def test_no_model_summary_keeps_keyword_extracts_out_of_summary_body(self):
        self.assertFalse(self.pane.raw.get('source'))
        self.assertTrue(any(item['text'] for item in self.pane.raw['items']))
        self.assertEqual(set(self.pane.field_labels), set(FIELDS))
        for label in self.pane.field_labels.values():
            self.assertEqual(label.text(), '待生成')

    def test_model_response_from_old_records_is_not_saved(self):
        previous = copy.deepcopy(self.pane.raw)
        displayed = copy.deepcopy(self.pane.displayed)
        stale_result = copy.deepcopy(previous)
        stale_result['source'] = '模型概括 · 待人工核对'
        stale_result['items'][0]['text'] = '这是基于旧记录生成的摘要。'
        self.add_message('换货还没收到，现在改为退款')

        with patch.object(self.pane.ledger, 'save', wraps=self.pane.ledger.save) as save:
            self.pane.model_ready(stale_result)

        save.assert_not_called()
        self.assertEqual(self.pane.raw, previous)
        self.assertEqual(self.pane.displayed, displayed)
        self.assertEqual(self.pane.ledger.latest('S00001'), previous)
        self.assertNotEqual(self.pane.pending['fingerprint'], previous['fingerprint'])
        self.assertIn('未采用旧结果', self.pane.notice.text())

    def test_urgent_risk_does_not_wait_for_summary_update(self):
        old = self.pane.raw['fingerprint']
        self.add_message('用了之后红肿刺痛，现在在医院')
        self.pane.refresh_pending()
        self.assertEqual(self.pane.raw['fingerprint'], old)
        self.assertIn('P0', self.pane.urgent.text())
        self.assertIn('医院', self.pane.urgent.toolTip())
        self.assertNotIn('医院', self.pane.urgent.text())
        self.assertTrue(self.pane.update_button.isEnabled())

    def test_link_confirm_unlink_same_order_and_topic(self):
        self.add_message('换货还没收到', 'TEST_LINK')
        self.add_message('我还想咨询套装赠品', 'TEST_LINK')
        found = candidates(self.provider, 'S00001')
        self.assertTrue(any(c['session'] == 'TEST_LINK' for c in found))
        self.assertNotIn('TEST_LINK', self.pane.raw['coverage'])
        form = LinkDialog(self.pane)
        idx = next(i for i in range(form.choice.count()) if form.choice.itemData(i)['session'] == 'TEST_LINK')
        form.choice.setCurrentIndex(idx)
        form.topic.setCurrentText('商品与换货')
        form.actor.setText('测试员')
        def simulated_model():
            result = self.pane.generate()
            result['source'] = '模型概括 · 待人工核对'
            self.pane.model_ready(result)

        with patch.object(self.pane, 'generate_model', side_effect=simulated_model):
            form.commit(True)
        self.assertIn('TEST_LINK', self.pane.raw['coverage'])
        self.assertNotIn('商品咨询', self.pane.raw['topics'])
        form = LinkDialog(self.pane)
        form.choice.setCurrentIndex(idx)
        form.topic.setCurrentText('商品与换货')
        form.actor.setText('测试员')
        with patch.object(self.pane, 'generate_model', side_effect=simulated_model):
            form.commit(False)
        self.assertNotIn('TEST_LINK', self.pane.raw['coverage'])

    def test_no_same_order_candidate_no_invented_history(self):
        form = LinkDialog(self.pane)
        if not form.rows:
            self.assertFalse(form.confirm.isEnabled())
            self.assertIn('没有可确认', form.preview.toPlainText())
        form.close()


if __name__ == '__main__':
    unittest.main()
