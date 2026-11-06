import copy
import json
import unittest
from unittest.mock import Mock, patch

from requests import HTTPError, Timeout

from copilot.llm import ModelConfig
from copilot.summary import build_summary, FIELDS
from copilot.summary_llm import generate_summary, model_context, _check_current_request_state, SummaryValidationError
from test_summary import case


class SemanticSummaryTests(unittest.TestCase):
    def test_current_request_cannot_revive_confirmed_missing_goods_or_refund(self):
        goods = build_summary([case(texts=[
            ('买家', '包裹没收到货'), ('客服', '我去核实'), ('买家', '收到了，谢谢'),
        ])])
        money = build_summary([case(texts=[
            ('买家', '退款咋还没到账'), ('客服', '退款已原路退回'), ('买家', '哦哦收到了，谢谢'),
        ])])
        with self.assertRaisesRegex(ValueError, '已确认收货'):
            _check_current_request_state([{'field': '诉求', 'text': '要求核实未收到货原因'}], goods)
        with self.assertRaisesRegex(ValueError, '已确认收到退款'):
            _check_current_request_state([{'field': '诉求', 'text': '咨询退款为何仍未到账'}], money)
        _check_current_request_state([{'field': '诉求', 'text': '当前无新增诉求；已收到款'}], money)
        partial = build_summary([case(texts=[
            ('买家', '包裹没收到货'), ('客服', '先发补偿券并继续查货'), ('买家', '券收到了，货还没到'),
        ])])
        _check_current_request_state([{'field': '诉求', 'text': '货还没收到，继续等待查找'}], partial)

    def test_conditional_agent_options_are_not_buyer_selection(self):
        waiting = build_summary([case(texts=[
            ('买家', '货没收到'), ('客服', '若确认丢失可以补发或退款'), ('买家', '那等你们回复'),
        ])])
        with self.assertRaisesRegex(ValueError, '客户未选择'):
            _check_current_request_state([{'field': '诉求', 'text': '接受客服补发或退款方案'}], waiting)
        _check_current_request_state([{'field': '诉求', 'text': '等待客服核查后回复'}], waiting)

    @patch('copilot.summary_llm.requests.post')
    def test_stale_refund_request_is_retried_with_same_sources(self, post):
        summary = build_summary([case(texts=[
            ('买家', '退款咋还没到账'), ('客服', '退款已原路退回'), ('买家', '哦哦收到了，谢谢'),
        ])])
        summary['risk'] = {'level': 'P3', 'evidence': []}
        valid = {'items': [
            {'field': '经过概述', 'topic': '退款经过', 'text': '先询问退款，后确认收到。', 'refs': ['e0', 'e2']},
            {'field': '诉求', 'topic': '退款结果', 'text': '当前无新增诉求；客户确认已收到退款。', 'refs': ['e2']},
            {'field': '待解决', 'topic': '结束核对', 'text': '现有记录未显示新增待办。', 'refs': ['e2']},
            {'field': '建议', 'topic': '结束核对', 'action': 'close_review', 'refs': ['e2']},
        ]}
        stale = copy.deepcopy(valid)
        stale['items'][1]['text'] = '咨询退款为何仍未到账。'
        stale['items'][1]['refs'] = ['e0']
        post.side_effect = [self.response(stale), self.response(valid)]

        result = generate_summary(summary, self.config)

        self.assertEqual(post.call_count, 2)
        self.assertIn('客户已确认收到退款', post.call_args.kwargs['json']['messages'][-1]['content'])
        self.assertIn('当前无新增诉求', next(i['text'] for i in result['items'] if i['field'] == '诉求'))

    def setUp(self):
        self.summary = build_summary([case()])
        self.summary['risk'] = {'level': 'P0', 'evidence': []}
        self.config = ModelConfig('http://localhost:9000/v1', 'test')
        self.output = {'items': [
            {'field': '经过概述', 'topic': '换货经过', 'text': '消费者报告破损，客服承诺换货。', 'refs': ['e0', 'e1']},
            {'field': '诉求', 'topic': '换货', 'text': '消费者要求换货。', 'refs': ['e0']},
            {'field': '待解决', 'topic': '换货', 'text': '实际发出情况待核实。', 'refs': ['e1']},
            {'field': '建议', 'topic': '换货', 'action': 'replacement', 'refs': ['e0', 'e1']},
        ]}

    def response(self, output):
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': json.dumps(output, ensure_ascii=False)}}]}
        return response

    @patch('copilot.summary_llm.requests.post')
    def test_semantic_output_keeps_original_evidence_and_risk(self, post):
        self.output['items'][-1]['text'] = '这段模型自由动作不会被采用'
        post.return_value = self.response(self.output)
        before = copy.deepcopy(self.summary)
        result = generate_summary(self.summary, self.config)
        post.assert_called_once()
        self.assertEqual(self.summary, before)
        for key in ('risk', 'coverage', 'evidence', 'fingerprint'):
            self.assertEqual(result[key], before[key])
        self.assertEqual({i['field'] for i in result['items']}, set(FIELDS))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertTrue(all(ref in before['evidence'] for row in result['items'] for ref in row['refs']))
        self.assertNotIn('自由动作', result['items'][-1]['text'])

    @patch('copilot.summary_llm.requests.post')
    def test_unknown_evidence_actions_numbers_and_missing_fields_rejected(self, post):
        variants = []
        for path, value in [('refs', ['not-a-source']), ('text', '已赔偿999元。')]:
            out = copy.deepcopy(self.output)
            out['items'][0][path] = value
            variants.append(out)
        out = copy.deepcopy(self.output)
        out['items'][-1]['action'] = 'send_refund'
        variants.append(out)
        out = copy.deepcopy(self.output)
        out['items'][0]['text'] = '建议服用某药治疗'
        variants.append(out)
        variants.append({'items': self.output['items'][:-1]})
        for out in variants:
            post.return_value = self.response(out)
            with self.assertRaises(ValueError):
                generate_summary(self.summary, self.config)

    def test_minimal_context_masks_ids_and_email_and_rejects_overflow(self):
        summary = copy.deepcopy(self.summary)
        summary['evidence']['a/0']['原文'] = '订单1234567890，邮箱a@example.com，换货'
        context, mapping = model_context(summary)
        serialized = json.dumps(context)
        self.assertNotIn('1234567890', serialized)
        self.assertNotIn('a@example.com', serialized)
        self.assertNotIn('a/0', serialized)
        self.assertEqual(mapping['e0'], 'a/0')
        summary['evidence']['a/0']['原文'] = '长' * 40000
        with self.assertRaises(ValueError):
            model_context(summary)

    @patch('copilot.summary_llm.requests.post')
    def test_update_context_keeps_original_records_and_human_corrections_separate(self, post):
        summary = build_summary([case(texts=[
            ('买家', '商品破损，我要换货'),
            ('客服', '暂时没货，可以等待，也可以退款'),
            ('买家', '那退吧'),
        ])])
        original_context, original_mapping = model_context(summary)
        summary['previous_items'] = [
            {'field': '经过概述', 'topic': '换货经过', 'text': '此前曾要求换货。',
             'human_corrected': False},
            {'field': '诉求', 'topic': '换货', 'text': '人工核对时仍希望换货，需与新增消息核实。',
             'human_corrected': True},
        ]
        before = copy.deepcopy(summary)
        post.return_value = self.response(self.output)

        generate_summary(summary, self.config)

        context = json.loads(post.call_args.kwargs['json']['messages'][1]['content'])
        self.assertEqual(context['previous_summary_and_corrections'], summary['previous_items'])
        self.assertEqual(context['sources'], original_context['sources'])
        self.assertEqual(model_context(summary)[1], original_mapping)
        records = [json.loads(source['content'])['原文'] for source in context['sources']]
        self.assertEqual(records, ['商品破损，我要换货', '暂时没货，可以等待，也可以退款', '那退吧'])
        self.assertEqual(context['prior_topics'], [
            {'field': '经过概述', 'topic': '换货经过'},
            {'field': '诉求', 'topic': '换货'},
        ])
        self.assertEqual(summary, before)

    @patch('copilot.summary_llm.requests.post')
    def test_previous_summary_cannot_authorize_an_unsupported_fact(self, post):
        self.summary['previous_items'] = [
            {'field': '经过概述', 'topic': '补偿', 'text': '此前摘要声称已补偿999元。',
             'human_corrected': True},
        ]
        self.output['items'][0]['text'] = '已补偿999元。'
        post.return_value = self.response(self.output)

        with self.assertRaisesRegex(ValueError, '无来源数字'):
            generate_summary(self.summary, self.config)

    @patch('copilot.summary_llm.requests.post')
    def test_summary_exceeding_total_length_limit_is_rejected(self, post):
        for item in self.output['items'][:-1]:
            item['text'] = '待核实' * 35
        self.output['items'].append({
            'field': '待解决', 'topic': '另一个待核实事项',
            'text': '待核实' * 35, 'refs': ['e0'],
        })
        post.return_value = self.response(self.output)

        with self.assertRaisesRegex(ValueError, '摘要过长'):
            generate_summary(self.summary, self.config)

    @patch('copilot.summary_llm.requests.post')
    def test_invalid_output_gets_one_correction_with_unchanged_sources(self, post):
        invalid = copy.deepcopy(self.output)
        invalid['items'][-1]['refs'] = []
        post.side_effect = [self.response(invalid), self.response(self.output)]
        before = copy.deepcopy(self.summary)

        result = generate_summary(self.summary, self.config)

        self.assertEqual(post.call_count, 2)
        first, second = [call.kwargs['json'] for call in post.call_args_list]
        self.assertEqual(first['messages'], second['messages'][:2])
        self.assertEqual(json.loads(second['messages'][-2]['content']), invalid)
        self.assertIn('建议 / 换货', second['messages'][-1]['content'])
        self.assertIn('refs', second['messages'][-1]['content'])
        self.assertEqual(result['items'][-1]['refs'], ['a/0', 'a/1'])
        self.assertEqual(result['evidence'], before['evidence'])
        self.assertEqual(self.summary, before)

    @patch('copilot.summary_llm.requests.post')
    def test_invalid_json_can_be_corrected_once(self, post):
        invalid = self.response(self.output)
        invalid.json.return_value['choices'][0]['message']['content'] = '{"items":'
        post.side_effect = [invalid, self.response(self.output)]

        result = generate_summary(self.summary, self.config)

        self.assertEqual(post.call_count, 2)
        self.assertEqual({item['field'] for item in result['items']}, set(FIELDS))
        self.assertIn('Expecting value', post.call_args.kwargs['json']['messages'][-1]['content'])


    @patch('copilot.summary_llm.requests.post')
    def test_two_invalid_outputs_stop_without_filling_missing_refs(self, post):
        self.output['items'][-1]['refs'] = []
        post.return_value = self.response(self.output)
        before = copy.deepcopy(self.summary)

        with self.assertRaisesRegex(ValueError, 'refs'):
            generate_summary(self.summary, self.config)

        self.assertEqual(post.call_count, 2)
        self.assertEqual(self.summary, before)

    @patch('copilot.summary_llm.requests.post')
    def test_rejected_amount_keeps_draft_reason_and_cited_sources(self, post):
        invalid = copy.deepcopy(self.output)
        invalid['items'][1]['text'] = '等待40元到账。'
        invalid['items'][1]['refs'] = ['e0']
        post.return_value = self.response(invalid)

        with self.assertRaises(SummaryValidationError) as caught:
            generate_summary(self.summary, self.config)

        self.assertIn('诉求 / 换货', str(caught.exception))
        self.assertIn('40', str(caught.exception))
        self.assertEqual(json.loads(caught.exception.draft), invalid)
        self.assertEqual(caught.exception.sources[0]['ref'], 'e0')
        self.assertEqual(post.call_count, 2)

    @patch('copilot.summary_llm.requests.post')
    def test_http_and_network_failures_are_not_retried(self, post):
        failed = self.response(self.output)
        failed.status_code = 500
        failed.raise_for_status.side_effect = HTTPError('unavailable')
        post.return_value = failed

        with self.assertRaises(HTTPError):
            generate_summary(self.summary, self.config)
        post.assert_called_once()

        post.reset_mock()
        post.side_effect = Timeout('timed out')
        with self.assertRaises(Timeout):
            generate_summary(self.summary, self.config)
        post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
