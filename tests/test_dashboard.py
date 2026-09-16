import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot.data import DEFAULT_SOURCE, ROOT
from copilot.store import ReviewStore, overdue


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = ReviewStore(self.path)
        self.args = dict(session="S00268", cutoff="2026-05-15 13:12:43", original="建议",
                         edited="建议", source="本地模板", risk={"level": "P0", "evidence": []},
                         decision="采纳", operator="客服", owner="甲", reason="核实", confirmed=True)
        self.store.save(**self.args)

    def update(self, status, **extra):
        args = dict(expected_updated=self.store.task("S00268")["updated"], owner="乙",
                    status=status, operator="主管", reason="已核实处理结果", confirmed=True)
        return self.store.update_task("S00268", **{**args, **extra})

    def test_lifecycle_and_reopen(self):
        for state in ("处理中", "已解决", "已关闭"):
            self.update(state)
        reopened = ReviewStore(self.path)
        self.assertEqual(reopened.task("S00268")["status"], "已关闭")
        self.assertEqual(len(reopened.events("S00268")), 4)
        with self.assertRaises(ValueError):
            reopened.save(**{**self.args, "reason": "新审核"})
        self.update("处理中")
        self.assertEqual(self.store.task("S00268")["status"], "处理中")

    def test_invalid_stale_unconfirmed_and_noop(self):
        old = self.store.task("S00268")["updated"]
        for state, extra in (("已关闭", {}), ("处理中", {"confirmed": False}),
                             ("处理中", {"reason": " "})):
            with self.assertRaises(ValueError):
                self.update(state, **extra)
        self.assertEqual(len(self.store.events("S00268")), 1)
        self.update("处理中")
        with self.assertRaises(ValueError):
            self.update("已解决", expected_updated=old)
        self.assertFalse(self.update("处理中"))
        self.assertEqual(len(self.store.events("S00268")), 2)

    def test_overdue_boundary_and_closed(self):
        task = self.store.task("S00268")
        created = datetime.fromisoformat(task["created"])
        self.assertFalse(overdue(task, now=created + timedelta(hours=24)))
        self.assertTrue(overdue(task, now=created + timedelta(hours=25)))
        self.assertFalse(overdue({**task, "status": "已解决"}, now=created + timedelta(days=2)))

    @unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
    def test_page_lifecycle_and_shared_history(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {"COPILOT_STATE_PATH": str(self.path)}):
            page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            self.assertFalse(page.exception)
            for state in ("处理中", "已解决", "已关闭"):
                page.text_input(key="board_owner").set_value("乙")
                page.text_input(key="board_actor").set_value("主管")
                page.text_area(key="board_note").set_value("核实后更新")
                page.selectbox(key="board_status").set_value(state)
                page.checkbox(key="board_confirm").check()
                page.button(key="board_save").click().run()
                self.assertFalse(page.exception)
                self.assertEqual(self.store.task("S00268")["status"], state)
                self.assertTrue(any(f"本地任务 S00268 · {state}" in item.value for item in page.info))
            fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            self.assertFalse(fresh.exception)
            self.assertTrue(any("已关闭" in item.value for item in fresh.info))
            fresh.selectbox(key="board_filter").set_value("待处理").run()
            self.assertTrue(any("没有符合条件" in item.value for item in fresh.info))
