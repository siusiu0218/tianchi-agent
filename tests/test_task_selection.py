from copy import deepcopy
import unittest
from scripts.evaluate_task_selection_live import validate
from copilot.task_guard_prototype import review_tasks


class TaskSelectionTests(unittest.TestCase):
    def setUp(self):
        self.context = {'messages': [{'ref': 'M1', 'text': '红肿刺痛', 'role': '买家'}],
                        'system_sources': [{'ref': 'S1', 'text': '系统已关联订单'}], 'risk_level': 'P0'}
        self.value = {'tasks': [{'type': 'verify_discomfort', 'evidence': [{'ref': 'M1', 'quote': '红肿刺痛'}]}], 'questions': []}

    def test_model_scope_is_not_approved_scope(self):
        result = validate(self.value, self.context)
        self.assertFalse(result['automatic_reply_allowed'])
        self.assertEqual(result['status'], 'needs_scope_review')
        guard = review_tasks(self.value, {**self.context, 'scope_origin': result['scope_origin']}, '原稿')
        self.assertEqual(guard['status'], 'blocked')
        self.assertEqual(guard['draft'], '原稿')

    def test_free_text_and_wrong_evidence_rejected(self):
        for mode in ('text', 'quote'):
            value = deepcopy(self.value)
            if mode == 'text':
                value['tasks'][0]['text'] = '必须提供原件'
            else:
                value['tasks'][0]['evidence'][0]['quote'] = '已退款'
            with self.assertRaises(ValueError):
                validate(value, self.context)

    def test_p0_and_known_order_boundaries(self):
        value = deepcopy(self.value)
        value['tasks'][0]['type'] = 'verify_exchange'
        with self.assertRaises(ValueError):
            validate(value, self.context)
        value = deepcopy(self.value)
        value['questions'] = [{'type': 'order', 'evidence': [{'ref': 'S1', 'quote': '系统已关联订单'}]}]
        with self.assertRaises(ValueError):
            validate(value, self.context)
