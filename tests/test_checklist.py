import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication, QCheckBox, QToolButton

from copilot.checklist import ChecklistStore, suggestions
from desktop.checklist import ChecklistWidget, ReadOnlyChecklist


class ChecklistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ChecklistStore(Path(self.temp.name) / 'state.sqlite3', 'workbook-one')
        self.session = 'S00001'
        self.proposed = [dict(source_key='待解决:商品与换货:发出', source_hash='source-a',
                              text='确认补发是否实际发出', refs=['S00001/m1'])]

    def test_suggestions_split_exchange_into_checkable_steps(self):
        summary = {'items': [{'id': '待解决:商品与换货', 'field': '待解决', 'topic': '商品与换货',
                              'text': '核实是否实际发出、是否收到；另需核对旧商品寄回安排。',
                              'source_hash': 'x', 'refs': ['S00001/m1']}]}
        self.assertEqual([item['text'] for item in suggestions(summary)],
                         ['确认补发是否实际发出', '确认客户是否收到补发商品且商品完好', '确认旧商品寄回安排是否落实'])

    def test_append_edit_check_reopen_and_deleted_suggestion(self):
        self.assertEqual(self.store.sync(self.session, self.proposed), 1)
        original = self.store.items(self.session)[0]
        self.store.edit(original['id'], '确认补发物流已发出', '客服甲')
        self.store.set_done(original['id'], True, '客服甲', 'S00001/m1')
        self.assertEqual(self.store.sync(self.session, self.proposed), 0)
        rows = ChecklistStore(self.store.path, 'workbook-one').items(self.session)
        self.assertEqual(rows[0]['text'], '确认补发物流已发出')
        self.assertEqual(rows[0]['done'], 1)
        self.store.set_done(original['id'], False, '客服甲')
        self.store.delete(original['id'], '客服甲')
        self.assertEqual(self.store.sync(self.session, self.proposed), 0)
        self.assertEqual(self.store.items(self.session), [])
        changed = [{**self.proposed[0], 'source_hash': 'source-b'}]
        self.assertEqual(self.store.sync(self.session, changed), 1)
        self.assertEqual(len(self.store.items(self.session)), 1)
        self.assertEqual([event['action'] for event in self.store.events(original['id'])],
                         ['修改', '完成', '重新待办', '删除'])

    def test_retires_only_untouched_stale_suggestions(self):
        extra = {**self.proposed[0], 'source_key': '待解决:物流进度:事项',
                 'text': '物流进度待核实'}
        edited = {**self.proposed[0], 'source_key': '待解决:商品咨询:事项',
                  'text': '商品咨询待核实'}
        self.store.sync(self.session, [*self.proposed, extra, edited])
        rows = self.store.items(self.session)
        self.store.edit(rows[2]['id'], '人工核实商品问题', '客服甲')
        self.store.sync(self.session, self.proposed, retire_stale=True)
        self.assertEqual([row['text'] for row in self.store.items(self.session)],
                         ['确认补发是否实际发出', '人工核实商品问题'])
        self.assertEqual([event['action'] for event in self.store.events(rows[1]['id'])],
                         ['建议撤回'])

    def test_manual_item_needs_record_or_screenshot_before_checking(self):
        item_id = self.store.add(self.session, '确认客户已收货', '客服甲')
        with self.assertRaisesRegex(ValueError, '依据或附上截图'):
            self.store.set_done(item_id, True, '客服甲')
        screenshot = Path(self.temp.name) / 'proof.png'
        Image.new('RGB', (20, 20), 'white').save(screenshot)
        self.store.attach(item_id, screenshot, '客服甲')
        screenshot.unlink()
        row = self.store.items(self.session)[0]
        self.assertTrue(self.store.screenshot_path(row['files'][0]).is_file())
        self.store.set_done(item_id, True, '客服甲')
        self.assertEqual(self.store.items(self.session)[0]['done'], 1)

    def test_model_detail_adds_only_with_new_source(self):
        local = {'items': [{'id': '待解决:退款与费用', 'field': '待解决', 'topic': '退款与费用',
                            'text': '退款与费用：结果待核实。', 'source_hash': 'source-a',
                            'refs': ['S00001/m1']}]}
        self.store.sync(self.session, suggestions(local))
        model = {'items': [{**local['items'][0], 'authored': True,
                            'text': '核实运费是否实际到账。'}]}
        self.assertEqual(self.store.sync(self.session, suggestions(model)), 0)
        model['items'][0]['source_hash'] = 'source-b'
        model['items'][0]['refs'] = ['S00001/m1', 'S00001/m2']
        self.assertEqual(self.store.sync(self.session, suggestions(model)), 1)
        self.assertEqual(self.store.sync(self.session, suggestions(model)), 0)
        self.assertEqual(len(self.store.items(self.session)), 2)

    def test_editing_completed_item_returns_it_to_pending(self):
        self.store.sync(self.session, self.proposed)
        item_id = self.store.items(self.session)[0]['id']
        self.store.set_done(item_id, True, '客服甲', 'S00001/m1')
        self.store.edit(item_id, '确认客户收到补发商品', '客服乙')
        row = self.store.items(self.session)[0]
        self.assertEqual(row['done'], 0)
        self.assertEqual(row['completion_ref'], '')
        self.assertEqual([event['action'] for event in self.store.events(item_id)],
                         ['完成', '修改', '重新待办'])

    def test_staff_controls_and_director_read_only(self):
        self.store.sync(self.session, self.proposed)
        staff = ChecklistWidget(self.store, self.session, {'S00001/m1': {'原文': '补发待确认'}})
        director = ReadOnlyChecklist(self.store, self.session)
        self.assertEqual(len(staff.findChildren(QCheckBox)), 1)
        self.assertEqual(len(staff.findChildren(QToolButton)), 1)
        self.assertFalse(staff.findChildren(QToolButton)[0].icon().isNull())
        with patch('desktop.checklist.QInputDialog.getItem', return_value=('S00001/m1 · 补发待确认', True)):
            staff.findChildren(QCheckBox)[0].click()
        self.assertEqual(self.store.items(self.session)[0]['completion_ref'], 'S00001/m1')
        staff.findChildren(QCheckBox)[-1].click()
        self.assertEqual(self.store.items(self.session)[0]['done'], 0)
        screenshot = Path(self.temp.name) / 'staff-proof.png'
        Image.new('RGB', (16, 16), 'white').save(screenshot)
        with patch('desktop.checklist.QFileDialog.getOpenFileName', return_value=(str(screenshot), '')):
            staff.findChildren(QToolButton)[0].menu().actions()[2].trigger()
        self.assertEqual(len(self.store.items(self.session)[0]['files']), 1)
        with patch('desktop.checklist.QInputDialog.getItem', return_value=('截图：staff-proof.png · 本地截图', True)):
            staff.findChildren(QCheckBox)[-1].click()
        self.assertEqual(self.store.items(self.session)[0]['done'], 1)
        self.assertEqual(len(director.findChildren(QCheckBox)), 0)
        staff.close()
        director.close()


if __name__ == '__main__':
    unittest.main()
