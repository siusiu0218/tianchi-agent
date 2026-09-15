import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests

from copilot.agent import assess, run_case
from copilot.data import DEFAULT_SOURCE, ExcelProvider, ROOT
from copilot.llm import ModelConfig, generate_draft, model_context


def synthetic(text="用了之后红肿刺痛，现在在医院", role="买家"):
    return {"messages": [{"角色": role, "message_id": "m-test", "message_text": text}],
            "orders": [], "tickets": []}


class RuleTests(unittest.TestCase):
    def test_p0_and_evidence(self):
        result = assess(synthetic())
        self.assertEqual(result["level"], "P0")
        self.assertEqual([x["message_id"] for x in result["evidence"]], ["m-test"])

    def test_staff_message_does_not_trigger(self):
        self.assertEqual(assess(synthetic(role="客服"))["level"], "待核实")

    def test_negation_and_question(self):
        for text in ("没有过敏，也没有红肿", "会不会过敏", "是否需要就医", "你好"):
            with self.subTest(text=text):
                self.assertEqual(assess(synthetic(text))["level"], "待核实")

    def test_service(self):
        self.assertEqual(assess(synthetic("包裹破损，我要换货"))["level"], "P1")

    def test_labels_do_not_control_risk(self):
        case = synthetic("你好")
        case["scene_major"] = "不良反应"
        self.assertEqual(assess(case)["level"], "待核实")


class ModelTests(unittest.TestCase):
    def setUp(self):
        case = synthetic()
        self.result = {"case": case, "risk": assess(case), "draft": "本地模板"}
        self.config = ModelConfig("http://127.0.0.1:9999/v1", "test-model")

    def response(self, content):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": content}}]}
        return response

    @patch("copilot.llm.requests.post")
    def test_success_uses_real_contract(self, post):
        post.return_value = self.response('{"opening_id":"discomfort"}')
        before = copy.deepcopy(self.result)
        output = generate_draft(self.result, self.config)
        self.assertEqual(output["status"], "model")
        self.assertEqual(self.result, before)
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:9999/v1/chat/completions")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertIn("人工确认", output["text"])

    @patch("copilot.llm.requests.post")
    def test_invalid_or_unsafe_response_falls_back(self, post):
        for content in ('bad-json', '{"opening_id":"neutral"}',
                        '{"opening_id":"discomfort","reply":"已退款"}',
                        '{"opening_id":[]}', 'null', '{}'):
            with self.subTest(content=content):
                post.return_value = self.response(content)
                self.assertEqual(generate_draft(self.result, self.config)["status"], "fallback")

    @patch("copilot.llm.requests.post")
    def test_timeout_and_error(self, post):
        for error in (requests.Timeout("secret"), requests.HTTPError("secret")):
            post.side_effect = error
            output = generate_draft(self.result, self.config)
            self.assertEqual(output["status"], "fallback")
            self.assertNotIn("secret", str(output))

    @patch("copilot.llm.requests.post")
    def test_missing_config_does_not_send(self, post):
        self.assertEqual(generate_draft(self.result, ModelConfig("", ""))["status"], "fallback")
        post.assert_not_called()

    def test_context_minimization(self):
        self.result["case"]["messages"][0]["message_text"] = "订单1234567890 邮箱a@example.com"
        context = json.dumps(model_context(self.result), ensure_ascii=False)
        for excluded in ("1234567890", "a@example.com", "m-test", "orders"):
            self.assertNotIn(excluded, context)


@unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_hash = hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest()
        cls.provider = ExcelProvider()

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest() == cls.original_hash

    def test_golden_case(self):
        result = run_case(self.provider, "S00268")
        case = result["case"]
        self.assertEqual(result["risk"]["level"], "P0")
        self.assertEqual(case["cutoff"], "2026-05-15 13:12:43")
        self.assertEqual(len(case["messages"]), 1)
        self.assertEqual(case["messages"][0]["message_id"], "39881346881031.PNM")
        self.assertEqual(case["orders"][0]["订单号"], "6920156290763740456")
        self.assertEqual(case["tickets"], [])
        self.assertEqual(result["action_status"], "draft_only")
        self.assertEqual(result, run_case(self.provider, "S00268"))

    def test_future_ticket_and_status_excluded(self):
        before = self.provider.get_case("S00268", "2026-05-15 13:46:42")
        after = self.provider.get_case("S00268", "2026-05-15 13:46:43")
        self.assertEqual(before["tickets"], [])
        self.assertEqual(after["tickets"][0]["工单号"], "BLFY41232690")
        self.assertNotIn("任务状态", after["tickets"][0])
        self.assertNotIn("订单状态", after["orders"][0])

    def test_all_sessions_have_no_offline_labels(self):
        for session in self.provider.sessions():
            case = self.provider.get_case(session)
            encoded = json.dumps(case)
            for key in ("scene_major", "scene_minor", "is_target_buyer_message", "chat_content"):
                self.assertNotIn(key, encoded)
            self.assertTrue(all(isinstance(o["订单号"], str) for o in case["orders"]))

    def test_unknown_and_empty_history(self):
        with self.assertRaises(ValueError):
            self.provider.get_case("UNKNOWN")
        case = self.provider.get_case("S00268", "2000-01-01 00:00:00")
        self.assertEqual(case["messages"], [])
        self.assertEqual(case["orders"], [])
        self.assertEqual(case["tickets"], [])

    def test_page_interactions(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.selectbox[0].value, "S00268")
        self.assertIn("P0", page.error[0].value)
        page.select_slider[0].set_value(3).run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(len(page.chat_message), 3)
        page.selectbox[0].set_value("S00001").run()
        self.assertEqual(len(page.exception), 0)
        page.button[0].click().run()
        self.assertEqual(len(page.exception), 0)


if __name__ == "__main__":
    unittest.main()
