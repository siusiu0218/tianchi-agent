from pathlib import Path
import os
import sqlite3
import json
from html import escape

from dotenv import load_dotenv
import streamlit as st

from copilot.agent import run_case
from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.llm import ModelConfig, generate_draft, model_context
from copilot.store import ReviewStore, TRANSITIONS, overdue

load_dotenv(Path(__file__).with_name(".env"))
st.set_page_config(page_title="共情副驾", page_icon="💬", layout="wide")
st.title("共情副驾")
st.caption("美妆客服助手 · 本地案例回放 · 所有回复均为待审阅草稿")


def wrapped_text(value: str):
    st.markdown('<div style="white-space:pre-wrap;overflow-wrap:anywhere">' + escape(value) + '</div>', unsafe_allow_html=True)


@st.cache_resource
def get_provider(source: str, modified: int):
    return ExcelProvider(Path(source))


try:
    source = Path(os.getenv("COPILOT_DATA_PATH", str(DEFAULT_SOURCE)))
    provider = get_provider(str(source), source.stat().st_mtime_ns)
except (OSError, ValueError, ImportError):
    st.error("未能读取比赛工作簿。请按运行指南检查文件路径、表格字段和依赖。")
    st.stop()

with st.sidebar:
    st.header("选择案例")
    sessions = provider.sessions()
    selected = st.selectbox("会话编号", sessions, index=sessions.index("S00268") if "S00268" in sessions else 0, key="case_session")
    messages = provider.messages(selected)
    default = next((i + 1 for i, m in enumerate(messages) if m["角色"] == "买家"), 1)
    position = st.select_slider("回放到第几条消息", options=list(range(1, len(messages) + 1)), value=default, key=f"position_{selected}")
    cutoff = messages[position - 1]["发送时间"]
    later = sorted({t["创建时间"] for t in provider.ticket_snapshot(selected)
                    if t["创建时间"] and t["创建时间"] > messages[-1]["发送时间"]})
    if later:
        extra_time = st.selectbox("补充回放时点", ["按消息进度", *later], key=f"extra_time_{selected}")
        if extra_time != "按消息进度":
            cutoff = extra_time
            position = f"{position}_{extra_time}"
    st.caption(f"回放时点：{cutoff}")
    st.info("S00268 演示不适升级，S00001 演示破损换货。拖动消息进度或选择补充时点查看证据。")

result = run_case(provider, selected, cutoff)
case, risk = result["case"], result["risk"]
left, right = st.columns([1.2, 1])
with left:
    st.subheader("聊天记录")
    for msg in case["messages"]:
        with st.chat_message("user" if msg["角色"] == "买家" else "assistant"):
            st.caption(f"{msg['角色']} · {msg['发送时间']} · {msg['message_id']}")
            wrapped_text(msg["message_text"])
            if msg["image_path"] or msg["内容类型"] == "图片":
                st.warning("图片暂不可查看，本版未进行图片识别。")
    st.subheader("关联订单")
    if case["orders"]:
        st.dataframe(case["orders"], width="stretch", hide_index=True)
    else:
        st.info("暂未查询到此时点的关联订单。")
    st.subheader("回放时点的工单")
    if case["tickets"]:
        st.dataframe(case["tickets"], width="stretch", hide_index=True)
    else:
        st.info("按表中创建时间，此时点暂未查询到已创建工单。")
    st.caption(case["time_notice"])
    if result["service"]:
        st.subheader("物流／换货核实")
        service = result["service"]
        st.text(service["original_logistics"])
        st.text(service["replacement_logistics"])
        st.warning(service["image_notice"])
        st.text(service["next_step"])
        with st.expander("原订单与补发物流数据快照（不参与回放分析）"):
            st.caption("以下是工作簿快照，可能晚于当前回放时点。单号存在不代表已经发货、签收或换货完成；补发快递公司只属于补发物流。")
            shipping = provider.logistics_snapshot(selected)
            st.write("原订单物流")
            if shipping["original"]:
                st.dataframe(shipping["original"], hide_index=True)
            else:
                st.info("暂未查询到原订单物流快照。")
            st.write("补发／换货物流")
            if shipping["replacement"]:
                st.dataframe(shipping["replacement"], hide_index=True)
            else:
                st.info("暂未查询到补发物流快照，不能使用原订单单号代替。")
    with st.expander("查看工单数据快照（不参与本次分析）"):
        st.caption("这是工作簿保存的状态，不代表回放时点的状态；它可能与聊天中的说法存在时间差。")
        snapshot = provider.ticket_snapshot(selected)
        if snapshot:
            st.dataframe(snapshot, width="stretch", hide_index=True)
        else:
            st.info("工作簿中也未查询到关联工单。")

with right:
    st.subheader("处理提醒")
    (st.error if risk["level"] == "P0" else st.warning)(f"{risk['level']} · {risk['reason']}")
    st.caption("P0 表示本项目的最高处理优先级，不代表医学诊断或严重程度分级。规则仍需人工核实。")
    for evidence in risk["evidence"]:
        st.caption(f"依据：{evidence['message_id']}")
        wrapped_text(evidence["quote"])
    st.subheader("回复草稿")
    st.caption("本地模板 · 可先体验，无需模型密钥")
    st.text_area("待审阅内容", result["draft"], height=225, key=f"draft_{selected}_{position}")
    st.caption("编辑只保留在当前页面；不会发送给顾客，不会提交工单或执行退款。")
    with st.expander("使用大模型辅助措辞"):
        st.write("本版让模型选择共情措辞，订单事实与处理建议由程序填入。")
        base = st.text_input("接口地址（通常以 /v1 结尾）", os.getenv("LLM_BASE_URL", ""))
        model = st.text_input("模型名称", os.getenv("LLM_MODEL", ""))
        key = st.text_input("API Key（仅当前会话使用）", os.getenv("LLM_API_KEY", ""), type="password")
        st.caption("仅点击下方按钮才调用所填服务。聊天文字可能含个人信息；请先查看发送预览。")
        st.json(model_context(result), expanded=False)
        if st.button("调用模型生成草稿", type="primary"):
            try:
                config = ModelConfig(base, model, key)
                config.validate()
            except ValueError as exc:
                st.warning(str(exc))
            else:
                with st.spinner("正在生成……"):
                    st.session_state["model_draft"] = (selected, cutoff, generate_draft(result, config))
        saved = st.session_state.get("model_draft")
        if saved and saved[:2] == (selected, cutoff):
            output = saved[2]
            (st.success if output["status"] == "model" else st.warning)(output["notice"])
            st.text_area("模型辅助草稿", output["text"], height=225, key=f"model_{selected}_{position}")
    with st.expander("本次处理步骤"):
        for i, step in enumerate(result["trace"], 1):
            st.write(f"{i}. {step}")

    st.subheader("人工审核与处理记录")
    st.caption("本地模拟任务；确认后保存审核记录，不向顾客发送消息，不执行退款或提交外部工单。操作人姓名为手工记录，未接入登录认证。")
    try:
        store = ReviewStore(os.getenv("COPILOT_STATE_PATH", str(Path(__file__).parent / "artifacts" / "copilot.sqlite3")))
        sources = ["本地模板"]
        if saved and saved[:2] == (selected, cutoff):
            sources.append("模型辅助草稿" if saved[2]["status"] == "model" else "回退模板")
        review_source = st.selectbox("本次审核的草稿", sources, key=f"review_source_{selected}_{position}")
        if review_source == "本地模板":
            original = result["draft"]
            edited = st.session_state[f"draft_{selected}_{position}"]
        else:
            original = saved[2]["text"]
            edited = st.session_state[f"model_{selected}_{position}"]
        st.caption("将保存以下内容；如需修改，请编辑上方对应的草稿框。")
        wrapped_text(edited)
        review_context = (selected, cutoff, review_source, edited)
        if st.session_state.get("review_context") != review_context:
            for field, value in {"review_confirmed": False, "review_reason": "", "review_owner": "", "review_decision": "采纳"}.items():
                st.session_state[field] = value
            st.session_state["review_context"] = review_context
        with st.form(f"review_{selected}_{position}_{review_source}"):
            decision = st.selectbox("审核操作", ["采纳", "修改后确认", "驳回"], key="review_decision")
            operator = st.text_input("操作人", key="review_operator")
            owner = st.text_input("处理负责人（确认时必填）", key="review_owner")
            reason = st.text_area("审核原因（必填）", key="review_reason")
            st.caption("采纳或修改后确认：创建/更新本会话的本地待处理任务。驳回：仅保存审核记录，已有任务保持原状态。")
            confirmed = st.checkbox("我已核对内容，确认保存本次操作", key="review_confirmed")
            submit = st.form_submit_button("保存审核结果", key="save_review")
        if submit:
            try:
                review_id, created = store.save(
                    session=selected, cutoff=cutoff, original=original, edited=edited,
                    source=review_source, risk=risk, decision=decision, operator=operator,
                    owner=owner, reason=reason, confirmed=confirmed)
                st.success(f"审核记录 #{review_id} 已保存。" if created else f"审核记录 #{review_id} 已存在，本次未重复写入。")
            except ValueError as exc:
                st.warning(str(exc))
        task = store.task(selected)
        if task:
            st.info(f"本地任务 {selected} · {task['status']} · 负责人：{task['owner']}")
            with st.expander("任务处理时间线"):
                events = store.events(selected)
                if not events:
                    st.caption("此任务创建于看板上线前，创建依据请查看审核历史。")
                for event in events:
                    state = json.loads(event["after_state"])
                    st.text(f"{event['created']} · {event['operator']} · {state['status']} · {state['owner']}\n{event['reason']}")
        history = store.history(selected)
        if not history:
            st.caption("当前会话还没有已保存的审核记录。")
        for entry in history:
            with st.expander(f"审核 #{entry['id']} · {entry['decision']} · {entry['operator']} · {entry['created']}"):
                st.caption(f"回放时点：{entry['cutoff']} · 来源：{entry['source']} · 负责人：{entry['owner'] or '未指定'}")
                st.text("审核原因：" + entry["reason"])
                st.text("原始建议：\n" + entry["original"])
                st.text("审核内容：\n" + entry["edited"])
                st.json(entry["risk"], expanded=False)
    except (sqlite3.Error, OSError):
        st.error("处理记录暂时无法读写，请检查本地存储路径和权限；未确认保存成功前请勿关闭草稿。")

st.divider()
st.header("主管风险看板")
st.caption("展示人工确认后的本地模拟任务。姓名为手工记录，未接入主管权限认证；时间显示为 UTC。")
try:
    board_store = ReviewStore(os.getenv("COPILOT_STATE_PATH", str(Path(__file__).parent / "artifacts" / "copilot.sqlite3")))
    st.button("刷新看板", key="refresh_board")
    if notice := st.session_state.pop("board_notice", None):
        st.success(notice)
    threshold = st.number_input("演示超时阈值（小时，从本地任务创建时起计算）", min_value=1, max_value=720, value=24)
    st.caption("该阈值仅用于演示提醒，不是业务承诺；已解决和已关闭任务不计为当前超时。修改阈值不更改任务记录。")
    tasks = board_store.tasks()
    with st.container(horizontal=True):
        st.metric("已确认任务", len(tasks))
        st.metric("未解决", sum(t["status"] in {"待处理", "处理中"} for t in tasks))
        st.metric("P0 未解决", sum(json.loads(t["payload"])["risk"]["level"] == "P0" and t["status"] in {"待处理", "处理中"} for t in tasks))
        st.metric("当前超时", sum(overdue(t, threshold) for t in tasks))
    status_filter = st.selectbox("筛选状态", ["全部", *TRANSITIONS], key="board_filter")
    rows = [t for t in tasks if status_filter == "全部" or t["status"] == status_filter]
    if not rows:
        st.info("当前没有符合条件的任务。请先在上方审核并确认一个案例，或调整筛选条件。")
    else:
        st.dataframe([{"会话": t["session"], "风险": json.loads(t["payload"])["risk"]["level"],
                       "风险说明": json.loads(t["payload"])["risk"].get("reason", ""),
                       "负责人": t["owner"], "状态": t["status"], "创建时间": t["created"],
                       "最后更新": t["updated"], "当前超时": "是" if overdue(t, threshold) else "否"}
                      for t in rows], hide_index=True, width="stretch")
        picked = st.selectbox("查看任务", [t["session"] for t in rows], key="board_task")
        current = next(t for t in rows if t["session"] == picked)
        rendered_version = st.session_state.get("board_rendered_version", (picked, current["updated"]))
        payload = json.loads(current["payload"])
        task_context = (picked, current["updated"])
        if st.session_state.get("task_form_context") != task_context:
            for field, value in {"board_confirm": False, "board_note": "", "board_owner": current["owner"], "board_status": current["status"]}.items():
                st.session_state[field] = value
            st.session_state["task_form_context"] = task_context
        st.subheader(f"任务 {picked} · {current['status']}")
        with st.expander("查看确认内容与原始案例证据"):
            st.caption(f"审核 #{current['review_id']} · 回放时点：{payload['cutoff']}")
            st.text(payload["edited"])
            st.json(payload["risk"], expanded=False)
            try:
                detail = provider.get_case(picked, payload["cutoff"])
                for message in detail["messages"]:
                    st.text(f"{message['message_id']} · {message['角色']}\n{message['message_text']}")
                st.write("关联订单")
                st.dataframe(detail["orders"], hide_index=True)
                st.write("回放时点的工单")
                st.dataframe(detail["tickets"], hide_index=True)
            except ValueError:
                st.warning("当前数据源无法找到原案例；已保存的审核和风险证据仍可查看。")
        with st.form(f"task_update_{picked}_{current['updated']}"):
            assigned = st.text_input("分派负责人", key="board_owner")
            next_status = st.selectbox("更新为", TRANSITIONS[current["status"]], key="board_status")
            actor = st.text_input("本次操作人", key="board_actor")
            note = st.text_area("处理说明／解决结果（必填）", key="board_note")
            confirm_task = st.checkbox("确认本次分派和状态变更", key="board_confirm")
            update = st.form_submit_button("保存任务变更", key="board_save")
        if update:
            try:
                if rendered_version != (picked, current["updated"]):
                    raise ValueError("任务已被其他操作更新，请刷新看板后重新核对。")
                changed = board_store.update_task(picked, expected_updated=current["updated"],
                    owner=assigned, status=next_status, operator=actor, reason=note, confirmed=confirm_task)
                st.session_state["board_notice"] = "任务已更新，客服处理记录已同步。" if changed else "负责人和状态未变化，未重复写入。"
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
        st.session_state["board_rendered_version"] = (picked, current["updated"])
        with st.expander("分派与状态变更记录", expanded=True):
            for event in board_store.events(picked):
                before = json.loads(event["before_state"])
                after = json.loads(event["after_state"])
                st.text(f"{event['created']} · {event['operator']}\n"
                        f"{before.get('status', '新建')} → {after['status']} · 负责人：{after['owner']}\n{event['reason']}")
except (sqlite3.Error, OSError):
    st.error("主管看板暂时无法读取或保存，请检查本地存储路径和权限。")
