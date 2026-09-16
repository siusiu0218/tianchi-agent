import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot.data import DEFAULT_SOURCE, ROOT


@unittest.skipUnless(DEFAULT_SOURCE.exists(), "本地比赛工作簿未提供")
class InboxTests(unittest.TestCase):
    def test_navigation_preserves_reply_and_search_switches_case(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"COPILOT_STATE_PATH": str(Path(temp) / "state.sqlite3")}):
                page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
                page.text_area(key="draft_S00268_history").set_value("尚未保存的人工回复").run()
                page.button(key="nav_board").click().run()
                self.assertEqual(page.session_state["workspace_tabs"], "风险看板")
                page.button(key="nav_inbox").click().run()
                self.assertEqual(page.text_area(key="draft_S00268_history").value, "尚未保存的人工回复")
                page.text_input(key="inbox_search").set_value("S00001").run()
                self.assertEqual([b.key for b in page.button if b.key and b.key.startswith("session_")], ["session_S00001"])
                page.button(key="session_S00001").click().run()
                self.assertEqual(page.selectbox(key="case_session").value, "S00001")
                self.assertFalse(page.checkbox(key="review_confirmed").value)
                page.selectbox(key="case_session").set_value(None).run()
                self.assertEqual(page.selectbox(key="case_session").value, "S00268")
                self.assertFalse(page.exception)


if __name__ == "__main__":
    unittest.main()
