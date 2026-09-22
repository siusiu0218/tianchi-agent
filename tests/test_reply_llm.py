import json
import unittest
from unittest.mock import Mock, patch

import requests

from copilot.llm import ModelConfig
from copilot.reply_llm import generate_reply, reply_context


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
