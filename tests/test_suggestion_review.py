import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from copilot.checklist import ChecklistStore
from copilot.task_guard_prototype import QUESTIONS
from desktop.suggestion_review import SuggestionReviewDialog


class SuggestionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ChecklistStore(Path(self.temp.name) / 'state.db', 'test')
        self.messages = [dict(message_id='M1', 角色='买家', message_text='脸发红刺痛，到现在没有加重也没减轻。')]
        self.item = self.store.add('S1', QUESTIONS['current_change'], 'tester', ['M1'])
        self.dialog = SuggestionReviewDialog(None, self.store, 'S1', {}, lambda: self.messages)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_known_answer_delete_keeps_audit(self):
        self.assertIn('到现在没有加重也没减轻', self.dialog.conflict.text())
        self.dialog.drop.click()
        self.assertFalse(self.store.items('S1'))
        self.assertEqual(len(self.store.items('S1', include_deleted=True)), 1)

    def test_keep_requires_reason_and_remains_pending_work(self):
        self.dialog.keep.click()
        self.assertIn('请说明', self.dialog.status.text())
        self.dialog.reason.setPlainText('核对记录是否仍适用于本次沟通')
        self.dialog.keep.click()
        row = self.store.items('S1')[0]
        self.assertIn('核对记录', row['text'])
        self.assertFalse(row['done'])

    def test_source_change_blocks_delete(self):
        self.messages.append(dict(message_id='M2', 角色='买家', message_text='刚才情况又变了'))
        self.dialog.drop.click()
        self.assertTrue(self.store.items('S1'))
        self.assertIn('来源或待办已变化', self.dialog.status.text())

    def test_other_edit_is_not_overwritten(self):
        self.store.edit(self.item, '另一位客服已修改', 'tester')
        self.dialog.drop.click()
        self.assertEqual(self.store.items('S1')[0]['text'], '另一位客服已修改')

    def test_unmatched_wording_is_not_automatically_suppressed(self):
        self.dialog.editor.setPlainText('需要重新了解情况')
        self.dialog.reason.setPlainText('人工核实')
        self.dialog.keep.click()
        self.dialog.show_item()
        self.assertFalse(self.dialog.answers)
        self.assertIn('不代表信息缺失', self.dialog.conflict.text())
