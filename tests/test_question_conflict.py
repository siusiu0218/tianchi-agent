from copy import deepcopy
import unittest
from copilot.question_conflict_prototype import gate_questions


class QuestionConflictTests(unittest.TestCase):
    def check_text(self, text, kind='current_change', role='买家'):
        return gate_questions([{'type': kind}], {'messages': [{'ref': 'M1', 'role': role, 'text': text}]})

    def test_saved_failure_suppressed_with_evidence(self):
        result = self.check_text('用了之后脸发红刺痛，昨晚八点开始，到现在没有加重也没减轻，目前在医院。')
        self.assertEqual(len(result['suppressed']), 1)
        self.assertEqual(result['suppressed'][0]['answer_evidence'][0]['quote'], '到现在没有加重也没减轻')
        self.assertEqual(result['customer_ready_questions'], [])

    def test_explicit_onset_and_change(self):
        for kind in ('onset', 'current_change'):
            self.assertEqual(len(self.check_text('使用后红肿刺痛，今天上午九点开始，现在已经缓解一些。', kind)['suppressed']), 1)

    def test_uncertainty_negation_reporting_not_suppressed(self):
        for text in ('红肿现在没有变化吗？', '朋友红肿现在没有变化', '我没说红肿现在没有变化',
                     '如果红肿现在没有变化怎么办', '医生说“红肿现在没有变化”', '红肿可能现在没有变化'):
            self.assertEqual(self.check_text(text)['suppressed'], [], text)

    def test_non_symptom_or_staff_statement_not_suppressed(self):
        self.assertEqual(self.check_text('现在没有变化的是物流状态')['suppressed'], [])
        self.assertEqual(self.check_text('有红肿，现在没有变化的是物流状态')['suppressed'], [])
        self.assertEqual(self.check_text('有红肿，今天上午九点开始上班', 'onset')['suppressed'], [])
        self.assertEqual(self.check_text('红肿现在没有变化', role='客服')['suppressed'], [])

    def test_older_current_state_not_assumed_current(self):
        context = {'messages': [{'ref': 'M1', 'role': '买家', 'text': '红肿现在没有变化'},
                                {'ref': 'M2', 'role': '买家', 'text': '后续怎么处理'}]}
        self.assertEqual(gate_questions([{'type': 'current_change'}], context)['suppressed'], [])

    def test_onset_conflict_goes_to_review(self):
        context = {'messages': [{'ref': 'M1', 'role': '买家', 'text': '刺痛昨晚八点开始'},
                                {'ref': 'M2', 'role': '买家', 'text': '刺痛今天上午九点开始'}]}
        self.assertEqual(gate_questions([{'type': 'onset'}], context)['suppressed'], [])

    def test_unknown_fields_remain_review_and_no_mutation(self):
        rows = [{'type': 'medical_material', 'evidence': [{'ref': 'M1', 'quote': '在医院'}]}]
        original = deepcopy(rows)
        result = gate_questions(rows, {'messages': []})
        self.assertEqual(rows, original)
        self.assertEqual(len(result['pending_staff_review']), 1)
        self.assertFalse(result['automatic_reply_allowed'])
