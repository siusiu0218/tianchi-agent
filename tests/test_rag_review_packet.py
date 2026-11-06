"""Offline evidence-export boundaries; no model requests or human approvals."""
from copy import deepcopy
import unittest

from copilot.rag_workflow_prototype import ReviewWorkflow
from scripts.export_rag_review_packet import packets, render
from scripts.rag_workflow_prototype import fixtures


class ReviewPacketTests(unittest.TestCase):
    def test_case_snapshot_is_complete_and_isolated(self):
        states = fixtures()
        flow = ReviewWorkflow(states)
        view = flow.view()
        self.assertEqual(view['case_snapshot'], states['SYN_A']['case'])
        self.assertEqual(view['cutoff'], states['SYN_A']['query'].at)
        view['case_snapshot']['orders'].append({'订单号': '000123456789012345678'})
        view['case_snapshot']['messages'][0]['message_text'] = 'changed'
        self.assertEqual(flow.view()['case_snapshot'], states['SYN_A']['case'])

    def test_render_preserves_business_ids_and_distinguishes_missing(self):
        packet = packets()[0]
        packet['snapshot']['case_snapshot']['orders'] = [{'订单号': '000123456789012345678'}]
        packet['snapshot']['case_snapshot']['tickets'] = [{'工单号': '000009', '状态': '待处理'}]
        text = render(packet)
        self.assertIn('000123456789012345678', text)
        self.assertIn('000009', text)
        self.assertIn(packet['snapshot']['cutoff'], text)
        self.assertIn('不证明业务未发生', text)
        packet['snapshot']['case_snapshot']['orders'] = []
        del packet['snapshot']['case_snapshot']['tickets']
        text = render(packet)
        self.assertIn('本快照记录为空。', text)
        self.assertIn('未提供该字段。', text)

    def test_updated_candidates_keep_conditions_and_unreviewed_state(self):
        data = packets()
        self.assertEqual(len(data), 8)
        for packet in data:
            self.assertEqual(packet['schema_version'], 2)
            self.assertEqual(packet['human_review']['status'], 'unreviewed')
            self.assertIsNone(packet['response_review']['overall'])
            text = ''.join(row['text'] for row in packet['sentence_reviews'])
            if packet['id'].endswith('annotated'):
                self.assertIn('预计48小时', text)
                self.assertNotIn('旧品寄回', text)
            if packet['id'].endswith('fixed'):
                self.assertIn('若涉及旧品寄回或运费', text)
            if packet['id'].startswith('SYN_B'):
                self.assertEqual(packet['snapshot']['risk']['level'], 'P0')

    def test_render_does_not_fill_human_reviews(self):
        packet = packets()[0]
        before = deepcopy(packet)
        render(packet)
        self.assertEqual(packet, before)


if __name__ == '__main__':
    unittest.main()
