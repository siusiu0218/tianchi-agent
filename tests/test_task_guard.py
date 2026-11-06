from copy import deepcopy
import unittest
from copilot.task_guard_prototype import review_tasks


class TaskGuardTests(unittest.TestCase):
    def setUp(self):
        self.context = {'messages': [{'ref': 'M1', 'text': '用后红肿'},
                                     {'ref': 'M2', 'text': '凭票报销，24小时回访'},
                                     {'ref': 'M3', 'text': '同意，图片发过了'}],
                        'scope_origin': 'source_reviewed',
                        'scope': {'verify_discomfort': ['M1'], 'verify_callback': ['M2', 'M3']},
                        'provided': {'image': ['M3']}, 'risk_level': 'P0'}
        self.candidate = {'tasks': [self.row('verify_discomfort', 'M1', '用后红肿'),
                                    {'type': 'verify_callback', 'evidence': [{'ref': 'M2', 'quote': '24小时回访'},
                                                                          {'ref': 'M3', 'quote': '同意'}]}], 'questions': []}

    def row(self, kind, ref, quote):
        return {'type': kind, 'evidence': [{'ref': ref, 'quote': quote}]}

    def test_historical_deadline_remains_only_in_evidence(self):
        result = review_tasks(self.candidate, self.context, '原稿')
        self.assertEqual(result['status'], 'needs_human_review')
        self.assertNotIn('24小时', ''.join(r['text'] for r in result['task_preview']))
        self.assertIn('24小时', str(result['task_preview'][1]['evidence']))
        self.assertEqual(result['draft'], '原稿')
        self.assertFalse(result['automatic_reply_allowed'])

    def test_free_text_originals_request_rejected(self):
        bad = deepcopy(self.candidate)
        bad['tasks'][1]['text'] = '客户必须提交票据原件，24小时回访'
        result = review_tasks(bad, self.context, '原稿')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['task_preview'], [])
        self.assertEqual(result['draft'], '原稿')

    def test_repeat_image_request_blocked(self):
        self.candidate['questions'] = [self.row('image', 'M3', '图片发过了')]
        self.assertIn('already_provided_check_internally', review_tasks(self.candidate, self.context)['issues'])

    def test_missing_discomfort_details_are_staff_reminders(self):
        result = review_tasks(self.candidate, self.context)
        self.assertEqual({r['type'] for r in result['staff_reminders']}, {'onset', 'current_change'})
        self.context['provided']['onset'] = ['M1']  # Caller-reviewed known state, not text inference.
        self.assertEqual([r['type'] for r in review_tasks(self.candidate, self.context)['staff_reminders']], ['current_change'])

    def test_unrelated_task_or_missing_agreement_ref_blocked(self):
        for task in [self.row('verify_exchange', 'M1', '用后红肿'), self.row('verify_callback', 'M2', '24小时回访')]:
            bad = deepcopy(self.candidate)
            bad['tasks'][1] = task
            self.assertEqual(review_tasks(bad, self.context)['status'], 'blocked')

    def test_missing_p0_or_unknown_quote_blocked(self):
        bad = deepcopy(self.candidate)
        bad['tasks'] = bad['tasks'][1:]
        self.assertIn('missing_p0_task', review_tasks(bad, self.context)['issues'])
        bad = deepcopy(self.candidate)
        bad['tasks'][0]['evidence'][0]['quote'] = '已退款'
        self.assertEqual(review_tasks(bad, self.context)['status'], 'blocked')

    def test_unknown_scope_fails_closed_and_input_is_unchanged(self):
        before = deepcopy(self.context)
        review_tasks(self.candidate, self.context)
        self.assertEqual(self.context, before)
        self.context['scope_origin'] = 'model_guess'
        self.assertEqual(review_tasks(self.candidate, self.context)['status'], 'blocked')
