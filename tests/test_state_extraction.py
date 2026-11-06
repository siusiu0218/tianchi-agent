from copy import deepcopy
import unittest
from scripts.evaluate_state_extraction_live import validate


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.context = {'messages': [{'ref': 'M1', 'role': '买家', 'text': '商品坏了'},
                                     {'ref': 'M2', 'role': '客服', 'text': '给您换货'}],
                        'system_sources': [{'ref': 'S0', 'text': '没有独立执行凭证'}]}
        evidence = [{'ref': 'M1', 'quote': '商品坏了'}]
        self.output = {'focus': {'value': 'product_issue', 'evidence': evidence},
                       'stage': {'value': 'initial_report', 'evidence': evidence},
                       'execution': {'value': 'unknown', 'evidence': [{'ref': 'S0', 'quote': '没有独立执行凭证'}]},
                       'known_information': [{'text': '客户报告商品坏了', 'origin': 'consumer_report', 'evidence': evidence}],
                       'missing_information': []}

    def test_structural_success_never_authorizes_reply(self):
        result = validate(self.output, self.context)
        self.assertFalse(result['semantic_verified'])
        self.assertFalse(result['automatic_reply_allowed'])

    def test_unknown_ref_or_invented_quote_rejected(self):
        for evidence in [[{'ref': 'M99', 'quote': '商品坏了'}], [{'ref': 'M1', 'quote': '已经退款'}]]:
            out = deepcopy(self.output)
            out['focus']['evidence'] = evidence
            with self.assertRaises(ValueError):
                validate(out, self.context)

    def test_execution_and_role_upgrade_rejected(self):
        for state in ('verified_complete', 'verified_incomplete'):
            out = deepcopy(self.output)
            out['execution']['value'] = state
            with self.assertRaises(ValueError):
                validate(out, self.context)
        out = deepcopy(self.output)
        out['known_information'][0]['origin'] = 'system_fact'
        with self.assertRaises(ValueError):
            validate(out, self.context)

    def test_staff_proposal_is_not_buyer_acceptance(self):
        self.output['stage'] = {'value': 'plan_accepted', 'evidence': [{'ref': 'M2', 'quote': '给您换货'}]}
        with self.assertRaises(ValueError):
            validate(self.output, self.context)
