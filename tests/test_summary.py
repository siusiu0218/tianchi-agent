import copy
import tempfile
import unittest
from pathlib import Path

from copilot.summary import build_summary, candidates, FIELDS
from copilot.summary_store import SummaryStore
from copilot.data import ExcelProvider


def case(session='a', texts=None):
    texts = texts or [('买家', '收到的商品破损，我要换货'), ('客服', '已登记换货，48小时内发出')]
    return {'session_id': session, 'cutoff': '2026-05-10 12:00:00', 'orders': [], 'tickets': [],
            'messages': [{'message_id': str(i), '角色': role, 'message_text': text,
                          '发送时间': f'2026-05-10 10:0{i}:00'} for i, (role, text) in enumerate(texts)]}


class SummaryTests(unittest.TestCase):
    def test_evidence_no_completion_from_promise(self):
        result = build_summary([case()])
        self.assertEqual({x['field'] for x in result['items']}, set(FIELDS))
        for item in result['items']:
            self.assertTrue(item['refs'])
            self.assertTrue(all(r in result['evidence'] for r in item['refs']))
        pending = [i['text'] for i in result['items'] if i['field'] == '待解决']
        self.assertTrue(any('待核实' in x for x in pending))

    def test_question_not_application_and_negation(self):
        result = build_summary([case(texts=[('买家', '没有过敏，请问可以退款吗')])])
        self.assertNotIn('使用不适', result['topics'])
        intent = next(i['text'] for i in result['items'] if i['field'] == '诉求')
        self.assertIn('请问可以退款吗', intent)
        self.assertNotIn('要求退款', intent)

    def test_snapshot_conflict_preserves_both(self):
        result = build_summary([case(texts=[('买家', '换货还没收到')])],
                               {'a': [{'工单号': 'x', '任务状态': '已完成'}]})
        text = '\n'.join(i['text'] for i in result['items'])
        self.assertIn('还没收到', text)
        self.assertIn('已完成', text)
        self.assertIn('记录不一致', text)

    def test_linked_topic_isolation(self):
        other = case('b', [('买家', '换货还没收到'), ('买家', '另外询问商品套装赠品')])
        result = build_summary([case(), other], selections={'b': ['商品与换货']})
        self.assertIn('b/0', result['evidence'])
        self.assertNotIn('b/1', result['evidence'])

    def test_multi_topic_link_does_not_introduce_unconfirmed_topic(self):
        other = case('b', [('买家', '换货还没收到，另外我要退款')])
        result = build_summary([case(), other], selections={'b': ['商品与换货']})
        self.assertNotIn('退款与费用', result['topics'])

    def test_no_receipt_inferred_from_expectation(self):
        for text in ['希望退款到账了就通知我', '退款还没到账了', '等钱到账了再说']:
            result = build_summary([case(texts=[('买家', text)])])
            self.assertFalse(any('消费者报告结果' in i['text'] for i in result['items']))

    def test_correction_restart_conflict_and_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite3'
            store = SummaryStore(path, 'dataset-one')
            result = build_summary([case()])
            item = result['items'][0]
            store.save('a', result)
            store.correct('a', item, '人工核实后的表述', '甲', '查阅证据')
            reopened = SummaryStore(path, 'dataset-one')
            self.assertEqual(reopened.latest('a'), result)
            displayed = reopened.apply('a', result)
            self.assertEqual(displayed['items'][0]['text'], '人工核实后的表述')
            self.assertFalse(displayed['items'][0]['conflict'])
            changed = copy.deepcopy(result)
            changed['items'][0]['source_hash'] = 'new'
            self.assertTrue(reopened.apply('a', changed)['items'][0]['conflict'])
            changed['items'] = changed['items'][1:]
            self.assertEqual(len(reopened.apply('a', changed)['orphaned_edits']), 1)
            self.assertEqual(SummaryStore(path, 'different-data').history('a'), [])

    def test_link_confirmation_removal_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SummaryStore(Path(tmp) / 'state.sqlite3', 'one')
            with self.assertRaises(ValueError):
                store.set_link('a', 'b', '商品与换货', True, '')
            store.set_link('a', 'b', '商品与换货', True, '甲')
            self.assertEqual(store.links('a'), {'b': ['商品与换货']})
            self.assertEqual(store.links('b'), {})
            store.set_link('a', 'b', '商品与换货', False, '甲')
            self.assertEqual(store.links('a'), {})

    def test_real_data_replay_and_no_hardcoded_case(self):
        provider = ExcelProvider()
        for session in ('S00001', 'S00268'):
            messages = provider.messages(session)
            result = build_summary([provider.get_case(session, messages[0]['发送时间'])])
            self.assertEqual(len(result['timeline']), 1)
            self.assertNotIn(messages[-1]['message_id'], str(result['evidence']))
        # Current supplied data may not include repeat contacts: no invented links.
        for row in candidates(provider, 'S00001'):
            self.assertTrue(row['orders'])

    def test_receipt_context_and_reopened_problem(self):
        c = case(texts=[('买家', '退款没到账'), ('客服', '退款原路退回，请核对账户'), ('买家', '哦哦收到了，虚惊一场')])
        result = build_summary([c])
        self.assertFalse(any(i['field'] == '待解决' and i['topic'] == '退款与费用' for i in result['items']))
        c['messages'].append({'message_id': 'later', '发送时间': '2026-05-10 11:00:00', '角色': '买家', 'message_text': '退款金额不对，还没退全'})
        result = build_summary([c])
        self.assertTrue(any(i['field'] == '待解决' and i['topic'] == '退款与费用' for i in result['items']))

    def test_actual_regressions_do_not_promote_optional_schemes(self):
        p = ExcelProvider()
        def summary(session):
            return build_summary([p.get_case(session, p.messages(session)[-1]['发送时间'])])
        self.assertNotIn('退款与费用', summary('S00018')['topics'])
        self.assertNotIn('退款与费用', summary('S00012')['topics'])
        self.assertNotIn('商品与换货', summary('S00040')['topics'])
        self.assertTrue(any(':结果' in x['topic'] for x in summary('S00056')['items']))
        self.assertIn('商品与换货', summary('S00102')['topics'])


if __name__ == '__main__':
    unittest.main()
