import os
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot.store import ReviewStore
from copilot.data import ROOT, DEFAULT_SOURCE


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = ReviewStore(self.path)
        self.args = dict(session="S00268", cutoff="2026-05-15", original="原稿",
                         edited="原稿", source="本地模板", risk={"level": "P0"},
                         decision="采纳", operator="客服甲", owner="主管乙",
                         reason="已核对", confirmed=True)

    def test_confirmation_required_and_rejection_creates_no_task(self):
        with self.assertRaises(ValueError):
            self.store.save(**{**self.args, "confirmed": False})
        self.assertEqual(self.store.history("S00268"), [])
        self.store.save(**{**self.args, "decision": "驳回", "owner": ""})
        self.assertIsNone(self.store.task("S00268"))
        self.assertEqual(len(self.store.history("S00268")), 1)

    def test_composed_send_is_atomic_and_retry_is_idempotent(self):
        draft = {'edited': '最终回复'}
        self.store.save_composer_draft('book-a', 'S00268', draft)
        self.store.save_composer_draft('book-b', 'S00268', {'edited': '另一本工作簿草稿'})
        args = dict(scope='book-a', session='S00268', token='send-1', original='AI 原稿',
                    edited='最终回复', source='AI 建议', cutoff='2026-05-15',
                    risk={'level': 'P0'}, operator='客服')
        with closing(self.store.connect()) as db, db:
            db.execute("CREATE TRIGGER fail_send BEFORE INSERT ON simulated_messages BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.Error):
            self.store.send_composed(**args)
        self.assertEqual(self.store.history('S00268'), [])
        self.assertIsNone(self.store.task('S00268'))
        self.assertEqual(self.store.composer_draft('book-a', 'S00268'), draft)
        with closing(self.store.connect()) as db, db:
            db.execute('DROP TRIGGER fail_send')
        first = self.store.send_composed(**args)
        second = self.store.send_composed(**args)
        self.assertTrue(first[1])
        self.assertEqual(second, (first[0], False))
        self.assertEqual(len(self.store.history('S00268')), 1)
        self.assertIsNone(self.store.composer_draft('book-a', 'S00268'))
        self.assertIsNotNone(self.store.composer_draft('book-b', 'S00268'))

    def test_concurrent_duplicate_and_reopen(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.save(**self.args), range(4)))
        self.assertEqual(sum(created for _, created in results), 1)
        reopened = ReviewStore(self.path)
        self.assertEqual(len(reopened.history("S00268")), 1)
        self.assertEqual(reopened.task("S00268")["owner"], "主管乙")
        self.assertIsNone(reopened.task("S00001"))

    def test_edit_audit_and_single_task(self):
        self.store.save(**self.args)
        with self.assertRaises(ValueError):
            self.store.save(**{**self.args, "edited": "修改稿"})
        self.store.save(**{**self.args, "edited": "修改稿", "decision": "修改后确认"})
        history = self.store.history("S00268")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["original"], "原稿")
        self.assertEqual(history[0]["edited"], "修改稿")
        self.assertEqual(self.store.task("S00268")["review_id"], history[0]["id"])

    @unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
    def test_page_confirm_refresh_and_new_session(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {"COPILOT_STATE_PATH": str(self.path)}):
            page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            self.assertFalse(page.exception)
            page.button(key="save_review").click().run()
            self.assertEqual(self.store.history("S00268"), [])
            page.text_input(key="review_operator").set_value("客服甲")
            page.text_input(key="review_owner").set_value("主管乙")
            page.text_area(key="review_reason").set_value("已核对证据")
            page.checkbox(key="review_confirmed").check()
            page.button(key="save_review").click().run()
            self.assertFalse(page.exception)
            self.assertEqual(len(self.store.history("S00268")), 1)
            page.button(key="save_review").click().run()
            self.assertEqual(len(self.store.history("S00268")), 1)
            fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            self.assertFalse(fresh.exception)
            self.assertTrue(any("主管乙" in item.value for item in fresh.info))
            fresh.selectbox(key="case_session").set_value("S00001").run()
            self.assertFalse(fresh.exception)
            self.assertFalse(any("本地任务 S00268" in item.value for item in fresh.info))
            self.assertFalse(fresh.checkbox(key="review_confirmed").value)
            self.assertEqual(fresh.text_area(key="review_reason").value, "")
            page.selectbox(key="case_session").set_value("S00001").run()
            self.assertFalse(page.checkbox(key="review_confirmed").value)
            self.assertEqual(page.text_input(key="review_owner").value, "")

    @unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
    def test_model_edit_is_the_reviewed_text(self):
        from streamlit.testing.v1 import AppTest
        from copilot.agent import run_case
        from copilot.data import ExcelProvider
        provider = ExcelProvider()
        result = run_case(provider, "S00268", provider.messages("S00268")[-1]["发送时间"])
        with patch.dict(os.environ, {"COPILOT_STATE_PATH": str(self.path)}):
            page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
            page.session_state["model_draft"] = (
                "S00268", result["case"]["cutoff"],
                {"status": "model", "text": "模型原稿", "notice": "测试模型"})
            page.run()
            page.selectbox(key="review_source_S00268_history").set_value("模型辅助草稿").run()
            page.text_area(key="model_S00268_history").set_value("人工修改稿").run()
            page.selectbox(key="review_decision").set_value("修改后确认")
            page.text_input(key="review_operator").set_value("客服甲")
            page.text_input(key="review_owner").set_value("主管乙")
            page.text_area(key="review_reason").set_value("核对后修改")
            page.checkbox(key="review_confirmed").check()
            page.button(key="save_review").click().run()
            self.assertFalse(page.exception)
            saved = self.store.history("S00268")[0]
            self.assertEqual(saved["source"], "模型辅助草稿")
            self.assertEqual(saved["original"], "模型原稿")
            self.assertEqual(saved["edited"], "人工修改稿")
