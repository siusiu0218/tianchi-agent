# 1. 规定 Agent 按什么顺序工作

from __future__ import annotations

import re

from copilot.data import CaseProvider

# These are conservative prototype rules, not clinically validated classifications.
SYMPTOMS = ("红肿", "刺痛", "过敏", "起疹", "肿胀", "瘙痒", "烂脸", "不良反应")
MEDICAL = ("医院", "就医", "急诊", "呼吸困难")
SERVICE = ("投诉", "12315", "一直没", "还没收到", "破损", "少件", "漏发", "换货", "退款")
OPENINGS = {
    "discomfort": "很抱歉您遇到这样的使用体验，您反馈的不适需要认真核实。",
    "waiting": "理解您等待处理的着急心情，也很抱歉给您带来困扰。",
    "neutral": "您好，感谢您说明情况，我会根据现有记录协助核实。",
}


def positive_mention(text: str, word: str) -> bool:
    for match in re.finditer(re.escape(word), text):
        prefix = text[max(0, match.start() - 7):match.start()]
        if not re.search(r"(没有|并无|未出现|不会|没|无|未|不是|是否|会不会|如果|假如|担心)(.{0,2})$", prefix):
            return True
    return False


def assess(case: dict) -> dict:
    symptoms, medical, service = [], [], []
    for msg in case["messages"]:
        if msg["角色"] != "买家":
            continue
        for words, bucket in ((SYMPTOMS, symptoms), (MEDICAL, medical), (SERVICE, service)):
            hits = [word for word in words if positive_mention(msg["message_text"], word)]
            if hits:
                bucket.append({"message_id": msg["message_id"], "quote": msg["message_text"], "matched": hits})
    if symptoms or medical:
        level, reason, evidence = "P0", "消费者自述不适或就医线索，建议人工优先核实并转专业人员。", symptoms + medical
    elif service:
        level, reason, evidence = "P1", "售后或投诉线索，建议人工核查处理进度。", service
    else:
        level, reason, evidence = "待核实", "当前规则未命中；不代表没有风险。", []
    unique = {item["message_id"]: item for item in evidence}
    return {"level": level, "reason": reason, "evidence": list(unique.values()),
            "rule_version": "prototype-1", "requires_human_review": True}


def compose(case: dict, risk: dict, opening_id: str) -> str:
    facts = []
    for order in case["orders"]:
        facts.append(f"关联订单 {order['订单号']} 的商品为“{order['商品名称']}”。")
    if not facts:
        facts.append("当前可见记录中暂未查询到关联订单，需要进一步核实。")
    facts.append(f"当前回放时点可查到 {len(case['tickets'])} 张已创建工单，处理进度需另行核实。")
    action = ("建议由客服优先核实并转交专业人员跟进；具体处理方案需人工确认。"
              if risk["level"] == "P0" else "建议由客服核实诉求与处理进度，再确认下一步安排。")
    return OPENINGS[opening_id] + "\n\n" + "".join(facts) + "\n\n" + action


def run_case(provider: CaseProvider, session_id: str, cutoff: str | None = None) -> dict:
    case = provider.get_case(session_id, cutoff)
    risk = assess(case)
    opening = "discomfort" if risk["level"] == "P0" else "waiting" if risk["level"] == "P1" else "neutral"
    return {"case": case, "risk": risk, "draft": compose(case, risk, opening),
            "draft_source": "本地模板（未调用大模型）", "action_status": "draft_only",
            "trace": ["读取可见聊天", "查询关联订单", "查询已创建工单", "执行提醒规则", "生成待人工审阅草稿"]}
