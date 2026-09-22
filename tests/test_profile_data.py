from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "赛题 1：数据共情者-业务数据.xlsx"
SCRIPT = ROOT / "scripts" / "profile_data.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProfileDataCliTest(unittest.TestCase):
    def test_cli_profiles_snapshot_without_modifying_source(self) -> None:
        source_hash_before = sha256(SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(SOURCE),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            profile = json.loads((output_dir / "profile.json").read_text(encoding="utf-8"))

            self.assertEqual(profile["source"]["sha256"], source_hash_before)
            self.assertEqual(profile["source"]["id_read_strategy"], "all cells read as strings")
            self.assertEqual(profile["summary"]["sheet_count"], 8)
            self.assertEqual(profile["summary"]["conversation_count"], 138)
            self.assertEqual(profile["summary"]["message_count"], 998)
            self.assertEqual(profile["summary"]["buyer_count"], 112)
            self.assertEqual(profile["summary"]["order_count"], 113)
            self.assertEqual(profile["summary"]["ticket_count"], 80)
            self.assertEqual(profile["summary"]["scene_major_count"], 10)
            self.assertEqual(profile["summary"]["scene_minor_count"], 41)
            self.assertEqual(profile["images"]["path_rows"], 29)
            self.assertEqual(profile["images"]["existing_files"], 0)

            checks = {item["check_id"]: item for item in profile["checks"]}
            self.assertEqual(len(checks), 19)
            self.assertTrue(all(item["status"] == "pass" for item in checks.values()))
            for check_id in (
                "message_id_unique_not_null",
                "order_id_unique_not_null",
                "ticket_id_unique_not_null",
                "orders_link_to_chat",
                "tickets_link_to_chat",
                "tickets_link_to_orders",
                "chat_order_refs_resolve",
                "chat_ticket_refs_resolve",
                "one_order_per_conversation",
                "one_ticket_per_conversation",
                "chat_order_refs_match_conversation",
                "chat_ticket_refs_match_conversation",
                "order_payment_time_or_deposit_annotation_valid",
                "order_shipping_fields_co_present",
                "ticket_completion_after_creation",
                "conversation_scene_labels_consistent",
            ):
                self.assertEqual(checks[check_id]["status"], "pass", check_id)

            self.assertEqual(
                checks["order_payment_time_or_deposit_annotation_valid"]["observed"]["deposit_annotation_rows"],
                3,
            )

            dictionaries = [
                path
                for path in (output_dir / "field-dictionaries").glob("*.md")
                if path.name != "README.md"
            ]
            self.assertEqual(len(dictionaries), 8)
            self.assertTrue((output_dir / "field-dictionaries" / "README.md").is_file())
            self.assertTrue((output_dir / "data-profile.md").is_file())

        self.assertEqual(sha256(SOURCE), source_hash_before)


if __name__ == "__main__":
    unittest.main()
