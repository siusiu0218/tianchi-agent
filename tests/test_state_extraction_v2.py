from copy import deepcopy
import unittest
from scripts.evaluate_state_extraction_v2_live import validate


class ExtractionV2Tests(unittest.TestCase):
    def setUp(self):
        self.context = {'messages': [{'ref': 'M1', 'role': '买家', 'text': '图发你了'}],
                        'system_sources': [{'ref': 'S0', 'text': '执行待核实'}, {'ref': 'S2', 'text': '附件原件不可见'}]}
        ref = [{'ref': 'M1', 'quote': '图发你了'}]
        self.value = {'issue_category': {'value': 'product_issue', 'evidence': ref},
                      'stage': {'value': 'initial_report', 'evidence': ref},
                      'current_tasks': [{'text': '核实图片反映的问题', 'evidence': ref}],
                      'already_provided': [{'text': '客户说已发图', 'origin': 'consumer_report', 'evidence': ref}],
                      'internal_verification': [{'item': '查看已有图片', 'reason': '当前不可见',
                                                'evidence': [{'ref': 'S2', 'quote': '附件原件不可见'}]}],
                      'customer_questions': [], 'execution': {'value': 'unknown', 'evidence': [{'ref': 'S0', 'quote': '执行待核实'}]}}

    def test_split_lists_and_no_automatic_reply(self):
        result = validate(self.value, self.context)
        self.assertFalse(result['automatic_reply_allowed'])
        self.assertFalse(result['semantic_verified'])
        self.assertEqual(self.value['customer_questions'], [])

    def test_task_quote_must_exist(self):
        value = deepcopy(self.value)
        value['current_tasks'][0]['evidence'] = [{'ref': 'M1', 'quote': '已经退款'}]
        with self.assertRaises(ValueError):
            validate(value, self.context)

    def test_missing_tasks_or_v1_fields_rejected(self):
        value = deepcopy(self.value)
        value['current_tasks'] = []
        with self.assertRaises(ValueError):
            validate(value, self.context)
        value = deepcopy(self.value)
        value['focus'] = value.pop('issue_category')
        with self.assertRaises(ValueError):
            validate(value, self.context)

    def test_bad_question_quote_and_execution_rejected(self):
        for change in ('quote', 'execution'):
            value = deepcopy(self.value)
            if change == 'quote':
                value['customer_questions'] = [{'item': '补图', 'reason': '测试错误引用', 'evidence': [{'ref': 'M99', 'quote': '未提供'}]}]
            else:
                value['execution']['value'] = 'verified_complete'
            with self.assertRaises(ValueError):
                validate(value, self.context)
