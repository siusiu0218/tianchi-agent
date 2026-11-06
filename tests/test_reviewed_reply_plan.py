from dataclasses import replace
import unittest

from copilot.rag_reply_prototype import prepare, propose, ReviewedReplyPlan
from scripts.rag_reply_prototype import good
from scripts.rag_workflow_prototype import fixtures


class ReviewedPlanTests(unittest.TestCase):
    def build(self, state, plan):
        return prepare(state['case'], state['query'], [], '原稿', reply_plan=plan)

    def test_missing_questions_only_and_p0_first(self):
        state = fixtures()['SYN_B']
        plan = ReviewedReplyPlan('compensation', ('SYN_B/M1',), ('current_change',))
        prepared = self.build(state, plan)
        text = propose(prepared, good, lambda: self.build(state, plan))['suggestion']
        self.assertTrue(text.startswith('您反馈的不适'))
        self.assertIn('目前的情况有没有变化', text)
        self.assertNotIn('什么时候', text)
        self.assertNotIn('换货', text)

    def test_invalid_source_and_stale_plan_cannot_be_used(self):
        state = fixtures()['SYN_A']
        with self.assertRaises(ValueError):
            self.build(state, ReviewedReplyPlan('exchange', ('foreign',)))
        plan = ReviewedReplyPlan('exchange', ('SYN_A/M1',))
        prepared = self.build(state, plan)
        changed = replace(plan, focus='compensation')
        result = propose(prepared, good, lambda: self.build(state, changed))
        self.assertNotEqual(result['status'], 'preview')
        self.assertEqual(result['draft'], '原稿')

    def test_risk_segment_cannot_be_omitted(self):
        state = fixtures()['SYN_B']
        plan = ReviewedReplyPlan('exchange', ('SYN_B/M1',))
        prepared = self.build(state, plan)
        def omit(context):
            return {'context_id': context['context_id'],
                    'segment_ids': [s for s in context['required_ids'] if s != 'priority_discomfort']}
        self.assertNotEqual(propose(prepared, omit, lambda: self.build(state, plan))['status'], 'preview')
