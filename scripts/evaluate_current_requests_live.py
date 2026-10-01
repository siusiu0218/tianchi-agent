"""Compare the configured summary API with confirmed conversation checkpoints.

Outputs stay in the ignored .scratch directory. No workbook copy, key, or raw
request body is written. --live is required before any network request.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot.agent import assess
from copilot.data import ExcelProvider
from copilot.llm import ModelConfig
from copilot.summary import build_summary
from copilot.summary_llm import PROMPT, generate_summary, model_context
from copilot import summary_llm
from desktop.config import load_model_settings, read_settings

GOLD = ROOT / "evaluation" / "current_request_gold.json"
DEFAULT_OUTPUT = ROOT / ".scratch" / "current-request-live"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def prepare(provider, row, omit_local_previous=False):
    messages = provider.messages(row["session"])
    cutoff = next((m for m in messages if m["message_id"] == row["cutoff_message_id"]), None)
    if cutoff is None:
        raise ValueError("标注回放消息不存在")
    case = provider.get_case(row["session"], cutoff["发送时间"])
    if case["messages"][-1]["message_id"] != row["cutoff_message_id"]:
        raise ValueError("回放时点无法精确定位到指定消息")
    # Match a first desktop AI-summary click: the previous summary is the local
    # summary for the same visible conversation. No historical ticket snapshots
    # are included because their mutable status would leak future information.
    summary = build_summary([case])
    summary["risk"] = assess(case)
    summary["previous_items"] = ([] if omit_local_previous else [
        {"field": item["field"], "topic": item["topic"], "text": item["text"], "human_corrected": False}
        for item in summary["items"]
    ])
    context, _ = model_context(summary)
    return summary, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="send the confirmed MOCK cases to the configured API")
    parser.add_argument("--session", help="run one session first")
    parser.add_argument("--cutoff-message-id", help="run only one checkpoint; requires --session")
    parser.add_argument("--force", action="store_true", help="repeat completed API calls")
    parser.add_argument("--omit-local-previous", action="store_true", help="compare a first AI summary without the local summary text")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prompt-file", type=Path, help="test a prompt without changing the desktop default")
    parser.add_argument("--cases-file", type=Path, default=GOLD)
    parser.add_argument("--include-provisional", action="store_true", help="include separately labeled, not user-confirmed checks")
    args = parser.parse_args()
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else PROMPT
    summary_llm.PROMPT = prompt
    if args.cutoff_message_id and not args.session:
        parser.error("--cutoff-message-id requires --session")
    rows = json.loads(args.cases_file.read_text(encoding="utf-8"))["cases"]
    rows = [row for row in rows if (row["review_status"] == "用户已确认" or args.include_provisional)
            and (not args.session or row["session"] == args.session)
            and (not args.cutoff_message_id or row["cutoff_message_id"] == args.cutoff_message_id)]
    if not rows:
        parser.error("没有匹配的已确认回放点")
    provider = ExcelProvider()
    prepared = [(row, *prepare(provider, row, args.omit_local_previous)) for row in rows]
    print(json.dumps({"checkpoints": len(prepared), "message_counts": [len(s["timeline"]) for _, s, _ in prepared],
                      "max_context_chars": max(len(json.dumps(c, ensure_ascii=False)) for _, _, c in prepared),
                      "network_call": args.live}, ensure_ascii=False), flush=True)
    if not args.live:
        return 0
    settings, key = load_model_settings(read_settings())
    config = ModelConfig(settings.get("base_url", ""), settings.get("model", ""), key)
    config.validate()
    args.output.mkdir(parents=True, exist_ok=True)
    failures = 0
    for row, summary, context in prepared:
        path = args.output / (row["session"] + "_" + row["cutoff_message_id"] + ".json")
        if path.exists() and not args.force:
            print(row["session"], row["cutoff_message_id"], "skipped_existing", flush=True)
            continue
        started = time.monotonic()
        record = {"session": row["session"], "cutoff_message_id": row["cutoff_message_id"],
                  "model": config.model, "endpoint_host": urlparse(config.base_url).hostname,
                  "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                  "context_sha256": digest(context), "gold_current_requests": row["current_requests"],
                  "label_status": row["review_status"],
                  "gold_other_state": row.get("resolved_or_accepted", []),
                  "local_previous_included": not args.omit_local_previous,
                  "source": "actual configured API call", "semantic_review": "pending"}
        attempts = []
        original_post = summary_llm.requests.post
        def traced_post(*positional, **kwargs):
            response = original_post(*positional, **kwargs)
            trace = {"http_status": response.status_code}
            if response.status_code == 200:
                envelope = response.json()
                trace["content"] = envelope.get("choices", [{}])[0].get("message", {}).get("content")
                trace["usage"] = envelope.get("usage")
            attempts.append(trace)
            return response
        try:
            with patch.object(summary_llm.requests, "post", side_effect=traced_post):
                result = generate_summary(summary, config)
            record["status"] = "validated_response"
            record["model_items"] = [{"field": x["field"], "topic": x["topic"], "text": x["text"], "refs": x["refs"]}
                                     for x in result["items"]]
        except Exception as exc:
            failures += 1
            record["status"] = "failed"
            record["error_type"] = type(exc).__name__
            record["error_message"] = str(exc)[:500]
        record["attempts"] = attempts
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(row["session"], row["cutoff_message_id"], record["status"], record["elapsed_seconds"], flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
