"""Evidence-bound logistics guidance from the visible replay only."""
WORDS = ("破损", "坏的", "按不出来", "少件", "漏发", "换货", "补发", "物流", "快递")


def service_summary(case):
    evidence = [{"message_id": m["message_id"], "quote": m["message_text"]}
                for m in case["messages"]
                if m["角色"] == "买家" and any(word in m["message_text"] for word in WORDS)]
    tickets = [t for t in case["tickets"] if t["工单类别"] == "补发换货工单"]
    if not evidence and not tickets:
        return None
    missing_image = any(m.get("image_path") or m.get("内容类型") == "图片" for m in case["messages"])
    return {"scene": "物流／破损／换货待核实", "evidence": evidence,
            "replacement_tickets": tickets,
            "original_logistics": "历史回放未提供可核实的原订单物流轨迹。",
            "replacement_logistics": "历史回放未提供可核实的补发发货时间与物流轨迹。",
            "image_notice": "存在图片消息，但图片未查看，无法确认破损。" if missing_image else "当前尚无可查看的图片证据。",
            "next_step": "请人工核实商品问题及可用图片、换货登记情况，再分别核对原订单物流与补发物流；发货与运费安排须人工确认。"}
