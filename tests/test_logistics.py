import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot.agent import run_case
from copilot.data import DEFAULT_SOURCE, ExcelProvider, ROOT
from copilot.store import ReviewStore


@unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
class LogisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ExcelProvider()

    def test_golden_case_time_boundary_and_no_tracking_leak(self):
        initial = run_case(self.provider, "S00001")
        self.assertEqual(initial["risk"]["level"], "P1")
        self.assertEqual(initial["risk"]["evidence"][0]["message_id"], "20974795108539.PNM")
        before = run_case(self.provider, "S00001", "2026-05-05 10:29:44")
        after = run_case(self.provider, "S00001", "2026-05-05 10:29:45")
        self.assertEqual(before["service"]["replacement_tickets"], [])
        self.assertEqual(after["service"]["replacement_tickets"][0]["工单号"], "BH919209358357")
        for result in (initial, before, after):
            self.assertNotIn("773478190943155", json.dumps(result))
            self.assertNotIn("YT7667875838478", json.dumps(result))
            self.assertNotIn("48小时", result["draft"])
        self.assertIn("图片未查看", before["draft"])
        self.assertIn("不代表已经发货", after["draft"])

    def test_snapshot_separates_carriers_and_missing_fields(self):
        snapshot = self.provider.logistics_snapshot("S00001")
        self.assertEqual(snapshot["original"][0]["快递公司"], "中通快递")
        self.assertEqual(snapshot["replacement"][0]["快递公司"], "圆通快递")
        self.assertEqual(snapshot["replacement"][0]["补发物流单号"], "YT7667875838478")
        self.assertEqual(self.provider.logistics_snapshot("UNKNOWN"), {"original": [], "replacement": []})
        provider = ExcelProvider()
        frame = provider.frames["补发换货工单"]
        frame.loc[frame["会话ID"].eq("S00001"), "补发物流单号"] = ""
        self.assertEqual(provider.logistics_snapshot("S00001")["replacement"][0]["补发物流单号"], "")

    def test_page_replay_confirm_and_close_without_cross_case_updates(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.sqlite3"
            store = ReviewStore(path)
            baseline = run_case(self.provider, "S00268")
            store.save(session="S00268", cutoff=baseline["case"]["cutoff"], original=baseline["draft"],
                       edited=baseline["draft"], source="本地模板", risk=baseline["risk"],
                       decision="采纳", operator="甲", owner="乙", reason="核实", confirmed=True)
            with patch.dict(os.environ, {"COPILOT_STATE_PATH": str(path)}):
                page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
                page.selectbox(key="case_session").set_value("S00001").run()
                page.select_slider[0].set_value(3).run()
                self.assertFalse(page.exception)
                self.assertTrue(any("图片" in item.value for item in page.warning))
                page.selectbox(key="extra_time_S00001").set_value("2026-05-05 10:29:45").run()
                self.assertFalse(page.exception)
                page.text_input(key="review_operator").set_value("客服")
                page.text_input(key="review_owner").set_value("售后")
                page.text_area(key="review_reason").set_value("核对文字及工单，图片待补充")
                page.checkbox(key="review_confirmed").check()
                page.button(key="save_review").click().run()
                page.selectbox(key="board_task").set_value("S00001").run()
                for status in ("处理中", "已解决", "已关闭"):
                    page.selectbox(key="board_status").set_value(status)
                    page.text_input(key="board_actor").set_value("主管")
                    page.text_area(key="board_note").set_value("模拟验收，不代表实际完成换货")
                    page.checkbox(key="board_confirm").check()
                    page.button(key="board_save").click().run()
                    self.assertFalse(page.exception)
                self.assertEqual(store.task("S00001")["status"], "已关闭")
                self.assertEqual(store.task("S00268")["status"], "待处理")
