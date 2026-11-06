import json
import unittest
from unittest.mock import Mock, patch

import requests

from copilot.llm import ModelConfig
from copilot.reply_llm import generate_reply, reply_context
from copilot.summary import build_summary


class ReplyModelTests(unittest.TestCase):
    def setUp(self):
        self.result = {'case': {'messages': [
            {'角色': '买家', 'message_text': '商品破损，电话13812345678'},
            {'角色': '客服', 'message_text': '请保留包装'}]},
            'risk': {'level': 'P1'}, 'draft': '当前需核实换货进度。'}
        self.config = ModelConfig('http://localhost:9000/v1', 'test')

    def test_context_includes_staff_draft_and_local_history_with_redaction(self):
        context = reply_context(self.result, '帮我查一下 a@b.com', [{'content': '上次已说明需核实'}])
        self.assertNotIn('13812345678', json.dumps(context))
        self.assertNotIn('a@b.com', context['staff_draft'])
        self.assertEqual(len(context['messages']), 3)

    def test_success_failure_and_p0_boundary(self):
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': json.dumps({'reply': '我会协助核实换货进度。'})}}]}
        with patch('copilot.reply_llm.requests.post', return_value=response) as post:
            self.assertEqual(generate_reply(self.result, self.config, '我想查进度')['status'], 'model')
            payload = post.call_args.kwargs['json']
            self.assertIn('我想查进度', payload['messages'][1]['content'])
            self.result['risk']['level'] = 'P0'
            self.assertEqual(generate_reply(self.result, self.config)['status'], 'error')
        with patch('copilot.reply_llm.requests.post', side_effect=requests.Timeout):
            output = generate_reply(self.result, self.config, '客服原文')
        self.assertEqual(output['status'], 'error')
        self.assertEqual(output['text'], '')

    def test_reply_uses_corrected_summary_and_original_evidence_without_operator_data(self):
        case = {'session_id': 'test', 'cutoff': '2026-05-01', 'orders': [], 'tickets': [],
                'messages': [{'角色': '买家', 'message_id': 'private-id', '发送时间': '2026-05-01',
                              'message_text': '换货还没收到，电话13812345678'}]}
        summary = build_summary([case])
        item = summary['items'][0]
        item['text'] = '消费者仍在等待换货，先核对配送进度。'
        item['correction'] = {'actor': 'private-operator', 'reason': 'private-note'}
        context = reply_context(self.result, '', summary=summary)
        self.assertEqual(context['handover']['items'][0]['text'], item['text'])
        self.assertTrue(context['handover']['items'][0]['human_corrected'])
        self.assertIn('换货还没收到', context['handover']['sources'][0]['content'])
        encoded = json.dumps(context, ensure_ascii=False)
        for secret in ('private-id', 'private-operator', 'private-note', '13812345678'):
            self.assertNotIn(secret, encoded)
        item['conflict'] = True
        with self.assertRaises(ValueError):
            reply_context(self.result, '', summary=summary)
