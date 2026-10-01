"""Read-only review of hand-labeled current requests against local summaries.

This does not call the configured model API or assign an automatic semantic score.
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from copilot.data import ExcelProvider
from copilot.summary import build_summary


GOLD = Path(__file__).resolve().parents[1] / "evaluation" / "current_request_gold.json"
UI_OBSERVATIONS = GOLD.with_name("current_request_ui_observations.json")


def main():
    data = json.loads(GOLD.read_text(encoding="utf-8"))
    ui = json.loads(UI_OBSERVATIONS.read_text(encoding="utf-8"))
    ui_by_session = {row["session"]: row for row in ui["observations"]}
    provider = ExcelProvider()
    counts = {"用户已确认": 0, "待用户复核": 0}
    for case in data["cases"]:
        session = case["session"]
        messages = provider.messages(session)
        positions = {row["message_id"]: index for index, row in enumerate(messages)}
        cutoff_id = case["cutoff_message_id"]
        if cutoff_id not in positions:
            raise ValueError(f"{session}: 回放消息不存在：{cutoff_id}")
        position = positions[cutoff_id]
        refs = list(case.get("evidence", [])) + list(case.get("context_evidence", []))
        for group in ("current_requests", "risk_clues"):
            refs.extend(ref for item in case.get(group, []) for ref in item["evidence"])
        if any(ref not in positions or positions[ref] > position for ref in refs):
            raise ValueError(f"{session}/{cutoff_id}: 证据超出回放时点或不存在")
        status = case["review_status"]
        counts[status] += 1
        result = build_summary([provider.get_case(session, messages[position]["发送时间"])])
        local = [item["text"] for item in result["items"] if item["field"] == "诉求"]
        print(f"\n### {session} / {cutoff_id} / {status}")
        expected = case["current_requests"]
        if case.get("resolved_or_accepted"):
            print("客户当前状态：" + "；".join(case["resolved_or_accepted"]))
        label = "人工答案" if status == "用户已确认" else "拟标注答案（待用户复核）"
        print(label + "：" + ("；".join(item["text"] for item in expected) if expected else "当前无新增请求"))
        print("本地摘要：" + ("；".join(local) if local else "未显示诉求"))
        print("本地核对：" + case["local_review"])
        observation = ui_by_session.get(session)
        if observation and cutoff_id == observation["gold_checkpoint_message_id"]:
            print("界面模型摘要截图：" + observation["current_request_display"])
            print("截图核对：" + observation["review"])
        print("真实 API 输出：本次未调用；截图对应的接口调用未核验")
    print(f"\n证据引用有效；共 {len(data['cases'])} 个回放点，用户已确认 {counts['用户已确认']}，待用户复核 {counts['待用户复核']}。")
    print("本地核对为当前工作区的人工语义检查，不是自动准确率；截图仅证明可见摘要文字，真实 API 质量尚无结论。")


if __name__ == "__main__":
    main()
