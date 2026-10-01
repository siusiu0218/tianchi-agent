import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from copilot.data import ExcelProvider
from copilot.summary import candidates, FIELDS, LOCAL_SOURCE
from copilot.checklist import suggestions
from copilot.summary_store import SummaryStore
from desktop.handover import HandoverPane, CorrectionDialog, HandoverEditDialog, LinkDialog, emphasize, rejected_draft_text


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
        self.pane.update_local()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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
        self.assertNotEqual(old, self.pane.raw['fingerprint'])
        self.assertTrue(self.pane.update_button.isEnabled())
        self.assertTrue(self.pane.changed)
        result = self.pane.generate()
        result['source'] = '模型概括 · 待人工核对'
        self.pane.model_ready(result)
        corrected = next(i for i in self.pane.displayed['items'] if i['id'] == item['id'])
        self.assertEqual(corrected['text'], '人工核实：希望换货')
        self.assertTrue(corrected['conflict'])
        with self.assertRaisesRegex(ValueError, '复核'):
            self.pane.reply_summary()

    def test_failed_update_keeps_prior_version(self):
        old = copy.deepcopy(self.pane.raw)
        result = self.pane.generate()
        result['source'] = '模型概括 · 待人工核对'
        with patch.object(self.pane.ledger, 'save', side_effect=OSError('test')):
            self.pane.model_ready(result)
        self.assertEqual(old, self.pane.raw)
        self.assertEqual(old, self.pane.ledger.latest('S00001'))
        self.assertIn('失败', self.pane.notice.text())

    def test_rejected_model_draft_is_reviewable_without_replacing_summary(self):
        before = copy.deepcopy(self.pane.raw)
        failure = {
            'reason': '诉求 / 补差价 含无来源数字 40；请核对该项 refs',
            'draft': '{"items":[{"field":"诉求","topic":"补差价","text":"等待40元到账","refs":["e0"]}]}',
            'sources': [{'ref': 'e0', 'content': '{"原文":"等待核实"}'}],
        }
        self.pane.model_rejected(failure)

        self.assertTrue(self.pane.rejected_button.isVisible())
        self.assertIn('40', self.pane.notice.text())
        self.assertIn('等待40元到账', rejected_draft_text(self.pane.rejected_draft))
        self.assertIn('e0：', rejected_draft_text(self.pane.rejected_draft))
        self.assertEqual(self.pane.raw, before)
        self.assertEqual(self.pane.ledger.latest('S00001'), before)
        result = self.pane.generate()
        result['source'] = '模型概括 · 待人工核对'
        self.pane.model_ready(result)
        self.assertIsNone(self.pane.rejected_draft)
        self.assertFalse(self.pane.rejected_button.isVisible())

    def test_four_fields_visible_and_model_text_stays_saved_until_update(self):
        result = self.pane.generate()
        result['source'] = '测试摘要 · 待人工核对'
        for item in result['items']:
            item['authored'] = True
            if item['field'] == '经过概述':
                item['text'] = '消费者报告商品破损。客服称已登记换货，消费者等待收货。'
        self.pane.model_ready(result)
        self.app.processEvents()
        self.assertFalse(self.pane.full_summary.isHidden())
        self.assertIn('未提供姓名', self.pane.consumer_label.text())
        self.pane.full_toggle.click()
        self.assertTrue(self.pane.full_summary.isHidden())
        self.pane.full_toggle.click()
        self.assertIn('消费者报告商品破损', self.pane.field_labels['经过概述'].text())
        old_lines = {f: label.text() for f, label in self.pane.field_labels.items()}
        self.add_message('现在不换货了，我想退款')
        self.pane.refresh_pending()
        self.assertEqual(old_lines, {f: label.text() for f, label in self.pane.field_labels.items()})
        self.assertIn('摘要待更新', self.pane.notice.text())
        with self.assertRaisesRegex(ValueError, '重新整理'):
            self.pane.reply_summary()

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

    def test_explicit_local_summary_visible_without_model(self):
        self.assertEqual(self.pane.raw.get('source'), LOCAL_SOURCE)
        self.assertTrue(any(item['text'] for item in self.pane.raw['items']))
        self.assertEqual(set(self.pane.field_labels), set(FIELDS))
        for label in self.pane.field_labels.values():
            self.assertNotEqual(label.text(), '待生成')
        self.assertIn('实际发出', self.pane.field_labels['待解决'].text())
        self.assertFalse(self.pane.full_summary.isHidden())
        self.assertEqual(self.pane.reply_summary()['fingerprint'], self.pane.raw['fingerprint'])

    def test_new_and_legacy_auto_sessions_stay_blank_until_generation(self):
        empty_path = Path(self.temp.name) / 'empty.sqlite3'
        blank = HandoverPane(self.provider, empty_path, 'S00070')
        self.assertIsNone(blank.ledger.latest('S00070'))
        self.assertEqual(blank.update_button.text(), '生成摘要')
        self.assertEqual({label.text() for label in blank.field_labels.values()}, {'待生成'})
        self.assertEqual(blank.checklist.items('S00070'), [])
        self.assertIsNone(blank.reply_summary())
        self.assertIn('P0', blank.urgent.text())
        blank.update_local()
        self.assertEqual(blank.raw['source'], LOCAL_SOURCE)
        self.assertTrue(blank.raw['explicit'])
        self.assertEqual(len(blank.checklist.items('S00070')), 2)
        blank.close()
        generated_again = HandoverPane(self.provider, empty_path, 'S00070')
        self.assertEqual(generated_again.raw['source'], LOCAL_SOURCE)
        self.assertEqual(len(generated_again.checklist.items('S00070')), 2)
        generated_again.close()

        legacy_path = Path(self.temp.name) / 'legacy.sqlite3'
        legacy = HandoverPane(self.provider, legacy_path, 'S00070')
        old = legacy.generate()
        old['source'] = LOCAL_SOURCE
        legacy.ledger.save('S00070', old)
        legacy.checklist.sync('S00070', suggestions(old))
        legacy.close()
        reopened = HandoverPane(self.provider, legacy_path, 'S00070')
        self.assertEqual({label.text() for label in reopened.field_labels.values()}, {'待生成'})
        self.assertEqual(reopened.update_button.text(), '生成摘要')
        self.assertEqual(reopened.checklist.items('S00070'), [])
        reopened.close()

    def test_old_fingerprint_with_same_sources_does_not_block_reply(self):
        self.pane.raw['source'] = '本地整理 · 待人工核对'
        self.pane.raw['fingerprint'] = 'older-summary-version'
        self.pane.pending = self.pane.generate()
        self.assertNotIn('有新记录', self.pane.notice_text())
        self.assertEqual(self.pane.reply_summary()['source'], '本地整理 · 待人工核对')

    def test_one_edit_dialog_updates_two_fields(self):
        dialog = HandoverEditDialog(self.pane)
        self.assertEqual(len(dialog.editors), sum(i['field'] != '待解决' for i in self.pane.displayed['items']))
        first = next((item, editor) for item, editor in dialog.editors if item['field'] == '诉求')
        second = next((item, editor) for item, editor in dialog.editors if item['field'] == '建议')
        first[1].setPlainText('人工核对后的客户诉求')
        second[1].setPlainText('人工核对后的建议方式')
        dialog.actor.setText('测试员')
        dialog.reason.setText('核对原文')
        dialog.save()
        edits = self.pane.ledger.history('S00001')
        self.assertEqual(len(edits), 2)
        self.assertEqual({row['edited'] for row in edits}, {'人工核对后的客户诉求', '人工核对后的建议方式'})
        self.assertFalse(any(item.get('conflict') for item in self.pane.reply_summary()['items']))

    def test_four_headings_have_evidence_and_one_edit_action(self):
        text = [button.text() for button in self.pane.findChildren(QPushButton)]
        self.assertEqual(text.count('修改接手要点'), 1)
        layout = self.pane.full_summary.layout()
        headings = [layout.itemAt(index).layout().itemAt(0).widget().text()
                    for index in range(0, layout.count(), 2)]
        self.assertEqual(headings, ['客户当前诉求：', '前期沟通情况：',
                                    '建议处理方式：', '待确认内容：'])
        evidence_buttons = self.pane.findChildren(QToolButton, 'evidenceButton')
        self.assertEqual(len(evidence_buttons), 4)
        self.assertTrue(all(button.toolTip() == '查看依据' and not button.icon().isNull()
                            and button.width() == 28 for button in evidence_buttons))
        with patch.object(self.pane, 'show_field') as show_field:
            evidence_buttons[0].click()
            show_field.assert_called_once_with('诉求')
        for title in ('客户当前诉求：', '前期沟通情况：', '待确认内容：', '建议处理方式：'):
            self.assertTrue(any(label.text() == title for label in self.pane.findChildren(type(self.pane.notice))))

    def test_multi_edit_conflict_saves_nothing(self):
        items = self.pane.displayed['items'][:2]
        self.pane.ledger.correct('S00001', items[1], '先前修改', '测试员', '核对原文')
        with self.assertRaisesRegex(ValueError, '已被修改'):
            self.pane.ledger.correct_many('S00001', [(items[0], '新的第一项'), (items[1], '新的第二项')], '测试员', '核对原文')
        self.assertEqual([row['edited'] for row in self.pane.ledger.history('S00001')], ['先前修改'])

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
        self.assertNotEqual(self.pane.raw['fingerprint'], old)
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
