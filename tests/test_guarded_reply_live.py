from copy import deepcopy
import unittest

from copilot.rag_reply_prototype import propose
from scripts.evaluate_reply_guarded_live import build_rows


class GuardedReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = build_rows()

    def test_fact_states_and_redaction(self):
        self.assertEqual(len(self.rows), 4)
        for row in self.rows:
            ctx = row['prepared']['context']
            self.assertEqual(ctx['fact_state']['execution'], 'unknown_no_independent_completion_evidence')
            self.assertTrue(ctx['fact_state']['order_linked'])
            self.assertNotIn('氯雷他定', str(ctx))
            if row['id'].endswith(('_4', '_8')):
                self.assertTrue(ctx['fact_state']['customer_agreement_refs'])
                self.assertTrue(ctx['fact_state']['historical_staff_statements'])

    def test_free_text_and_unknown_segments_rejected_keep_draft(self):
        for row in self.rows:
            p = row['prepared']
            for response in [
                {'context_id': p['context_id'], 'segment_ids': p['context']['required_ids'],
                 'reply': '已退款，运费由我们承担，请安心就医'},
                {'context_id': p['context_id'], 'segment_ids': ['已退款']},
            ]:
                result = propose(p, lambda _: response, lambda: p)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['draft'], '保留原稿')
                self.assertEqual(result['suggestion'], '')

    def test_required_clauses_p0_order_and_no_duplicate_questions(self):
        for row in self.rows:
            p = row['prepared']
            result = propose(p, lambda c: {'context_id': c['context_id'], 'segment_ids': list(reversed(c['required_ids']))}, lambda: p)
            self.assertEqual(result['status'], 'preview')
            text = result['suggestion']
            for unsafe in ('已退款', '已经记录', '立即转交', '安心就医', '运费由我们承担', '订单编号'):
                self.assertNotIn(unsafe, text)
            if row['id'].startswith('S00268'):
                self.assertTrue(text.startswith('您反馈的不适'))
                self.assertNotIn('换货', text)
            if row['id'] == 'S00268_8':
                self.assertNotIn('什么时候', text)
                self.assertNotIn('请提供', text)

    def test_changed_snapshot_rejects_old_result(self):
        p = self.rows[0]['prepared']
        new = deepcopy(p)
        new['context_id'] = 'updated-facts'
        new['draft'] = '新草稿'
        result = propose(p, lambda c: {'context_id': c['context_id'], 'segment_ids': c['required_ids']}, lambda: new)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['draft'], '新草稿')
