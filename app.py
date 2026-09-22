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
from copilot.ui import apply_style, bubble, conversation_header, fact

load_dotenv(Path(__file__).with_name(".env"))
st.set_page_config(page_title="共情副驾 · 收件箱", page_icon=":material/forum:", layout="wide")
apply_style()


def wrapped_text(value):
    st.markdown('<div style="white-space:pre-wrap;overflow-wrap:anywhere">' + escape(value) + '</div>', unsafe_allow_html=True)


def choose_session(session):
    st.session_state["case_session"] = session


def keep_session_selected(default):
    if not st.session_state.get("case_session"):
        st.session_state["case_session"] = default


def navigate(label):
    st.session_state["workspace_tabs"] = label


@st.cache_resource
def get_provider(source, modified):
    return ExcelProvider(Path(source))


try:
    source = Path(os.getenv("COPILOT_DATA_PATH", str(DEFAULT_SOURCE)))
    provider = get_provider(str(source), source.stat().st_mtime_ns)
except (OSError, ValueError, ImportError):
    st.error("无法读取数据，请检查工作簿路径和依赖。")
    st.stop()

with st.sidebar:
    st.html('<div class="brand"><span class="brand-mark">◔</span>共情副驾</div>')
    st.html('<div class="nav-label">工作空间</div>')
    active = st.session_state.get("workspace_tabs", "会话收件箱")
    st.button("会话收件箱", icon=":material/forum:", width="stretch", key="nav_inbox",
              type="primary" if active == "会话收件箱" else "tertiary",
              on_click=navigate, args=("会话收件箱",))
    st.button("风险看板", icon=":material/dashboard:", width="stretch", key="nav_board",
              type="primary" if active == "风险看板" else "tertiary",
              on_click=navigate, args=("风险看板",))
    st.html('<div class="nav-label">偏好设置</div>')
    with st.expander("模型连接", icon=":material/settings:"):
        base = st.text_input("接口地址", os.getenv("LLM_BASE_URL", ""))
        model = st.text_input("模型名称", os.getenv("LLM_MODEL", ""))
        api_key = st.text_input("API Key", os.getenv("LLM_API_KEY", ""), type="password")
        st.caption("点击生成建议时才会调用。")
    st.html('<div class="sidebar-note">本地工作空间<br>回复经人工确认后保存<br>尚未连接对外发送渠道</div>')

# Both views remain mounted to preserve editing state while navigating.
work_tab, board_tab = st.tabs(["会话收件箱", "风险看板"], key="workspace_tabs", on_change="rerun")
with work_tab:
    with st.container(key="inbox_grid"):
        inbox, conversation, inspector = st.columns([.85, 1.85, 1], gap="small")
    with inbox:
        st.subheader("会话", icon=":material/forum:")
        sessions = provider.sessions()
        if "case_session" not in st.session_state:
            st.session_state["case_session"] = "S00268" if "S00268" in sessions else sessions[0]
        selected = st.selectbox("搜索会话", sessions, index=None,
                                key="case_session", label_visibility="collapsed",
                                on_change=keep_session_selected, args=("S00268" if "S00268" in sessions else sessions[0],))
        query = st.text_input("搜索消息", placeholder="搜索消息内容…", key="inbox_search", label_visibility="collapsed")
        previews = {}
        for session in sessions:
            history = provider.messages(session)
            previews[session] = history[-1]["message_text"] if history else "暂无消息"
        ordered = list(dict.fromkeys([selected, *[s for s in ("S00268", "S00001") if s in sessions], *sessions]))
        visible = [s for s in ordered if not query or query.casefold() in (s + previews[s]).casefold()]
        st.caption(f"全部会话 · {len(visible)}")
        with st.container(height=580, border=False, key="session_list"):
            for session in visible:
                # Inbox preview shows the latest message in this conversation.
                summary = previews[session].replace("\n", " ")[:28]
                summary = summary.replace("*", "").replace("[", "").replace("]", "")
                st.button(f"**客户 · {session}**\n{summary}…", key=f"session_{session}", width="stretch",
                          type="primary" if session == selected else "tertiary", on_click=choose_session, args=(session,))
            if not visible:
                st.caption("没有匹配的会话。")

    messages = provider.messages(selected)
    # The inbox reads the full conversation; historical cutoffs remain in CLI/tests.
    cutoff = messages[-1]["发送时间"]
    position = "history"
    with conversation:
        conversation_header(selected)
        result = run_case(provider, selected, cutoff)
        case, risk = result["case"], result["risk"]
        with st.container(height=370, border=False, key="chat_feed", autoscroll=True):
            previous_day = None
            for msg in case["messages"]:
                day = msg["发送时间"][:10]
                if day != previous_day:
                    st.html(f'<div class="chat-date">{escape(day)}</div>')
                    previous_day = day
                with st.chat_message("user" if msg["角色"] == "买家" else "assistant", avatar=":material/person:" if msg["角色"] == "买家" else ":material/support_agent:"):
                    bubble(msg)
                    if msg["image_path"] or msg["内容类型"] == "图片":
                        st.warning("图片不可查看，尚未识别。")
        with st.container(key="composer"):
            st.markdown("**回复**")
            with st.expander("副驾建议", icon=":material/auto_awesome:"):
                st.caption("模型选择开场措辞，事实由已查询记录填入。")
                with st.expander("发送内容预览"):
                    st.json(model_context(result), expanded=False)
                if st.button("生成建议", key="generate_model", icon=":material/auto_awesome:"):
                    try:
                        config = ModelConfig(base, model, api_key)
                        config.validate()
                    except ValueError as exc:
                        st.warning(str(exc))
                    else:
                        with st.spinner("正在生成建议…"):
                            output = generate_draft(result, config)
                            st.session_state["model_draft"] = (selected, cutoff, output)
                            st.session_state[f"model_{selected}_{position}"] = output["text"]
                            st.session_state[f"review_source_{selected}_{position}"] = "模型辅助草稿" if output["status"] == "model" else "回退模板"
            saved = st.session_state.get("model_draft")
            sources = ["本地模板"]
            if saved and saved[:2] == (selected, cutoff):
                sources.append("模型辅助草稿" if saved[2]["status"] == "model" else "回退模板")
            if len(sources) > 1:
                review_source = st.selectbox("回复来源", sources, key=f"review_source_{selected}_{position}", label_visibility="collapsed")
            else:
                review_source = "本地模板"
            original = result["draft"] if review_source == "本地模板" else saved[2]["text"]
            edit_key = f"draft_{selected}_{position}" if review_source == "本地模板" else f"model_{selected}_{position}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = original
            edited = st.text_area("回复内容", value=None, height=155, key=edit_key, label_visibility="collapsed")
            st.caption("仅保存至本地，不会发送给客户。")
            with st.expander("确认并保存", icon=":material/check_circle:"):
                try:
                    store = ReviewStore(os.getenv("COPILOT_STATE_PATH", str(Path(__file__).parent / "artifacts" / "copilot.sqlite3")))
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
                        submit = st.form_submit_button("保存审核结果", key="save_review", type="primary", icon=":material/check_circle:", width="stretch")
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
                            st.caption(f"记录截至：{entry['cutoff']} · 来源：{entry['source']} · 负责人：{entry['owner'] or '未指定'}")
                            st.text("审核原因：" + entry["reason"])
                            st.text("原始建议：\n" + entry["original"])
                            st.text("审核内容：\n" + entry["edited"])
                            st.json(entry["risk"], expanded=False)

                except (sqlite3.Error, OSError):
                    st.error("处理记录暂时无法读写，请检查存储路径；请保留当前回复。")

    with inspector:
        with st.container(key="inspector"):
            st.subheader("客户与副驾", icon=":material/contact_page:")
            st.html(f'<div class="profile"><div class="avatar">客</div><strong>客户 · {escape(selected)}</strong><div class="meta">在线咨询</div></div>')
            st.html('<div class="section-label">处理优先级</div>')
            (st.error if risk["level"] == "P0" else st.warning)(f"{risk['level']} · {'优先核实并升级处理' if risk['level'] == 'P0' else '请人工核实'}")
            with st.expander("判断依据", expanded=False, icon=":material/verified_user:"):
                st.write(risk["reason"])
                for evidence in risk["evidence"]:
                    st.caption(evidence["message_id"])
                    wrapped_text(evidence["quote"])
                st.caption("P0 是处理优先级，不是医学诊断。")
            st.html('<div class="section-label">关联订单</div>')
            if case["orders"]:
                for order in case["orders"]:
                    fact("商品", order["商品名称"])
                    fact("订单号", order["订单号"])
                    fact("数量 / 下单时间", f"{order['数量']} 件 · {order['下单时间']}")
            else:
                st.caption("暂无关联订单。")
            with st.expander(f"工单记录 · {len(case['tickets'])}", icon=":material/confirmation_number:"):
                for ticket in case["tickets"]:
                    fact(ticket["工单类别"], ticket["工单号"])
                    st.caption(ticket["创建时间"])
                if not case["tickets"]:
                    st.caption("当前时点尚无已创建工单。")
            if result["service"]:
                with st.expander("物流与换货", icon=":material/local_shipping:"):
                    st.warning(result["service"]["image_notice"])
                    st.write(result["service"]["next_step"])
                    st.caption("以下为工作簿快照，不参与历史回放；单号不代表已发货。")
                    shipping = provider.logistics_snapshot(selected)
                    for label, rows in (("原订单物流", shipping["original"]), ("补发物流", shipping["replacement"])):
                        st.markdown(f"**{label}**")
                        for row in rows:
                            for name, value in row.items():
                                fact(name, value or "暂无")
                        if not rows:
                            st.caption("暂无记录。")
            with st.expander("证据与数据详情", icon=":material/description:"):
                st.caption(case["time_notice"])
                st.dataframe(case["orders"], hide_index=True)
                st.dataframe(case["tickets"], hide_index=True)
                st.caption("完整工单快照，仅供核对，不参与本次分析。")
                st.dataframe(provider.ticket_snapshot(selected), hide_index=True)


with board_tab:
    st.subheader("主管风险看板", icon=":material/dashboard:")
    st.caption("展示人工确认后的本地模拟任务。姓名为手工记录，未接入主管权限认证；时间显示为 UTC。")
    try:
        board_store = ReviewStore(os.getenv("COPILOT_STATE_PATH", str(Path(__file__).parent / "artifacts" / "copilot.sqlite3")))
        st.button("刷新看板", key="refresh_board", icon=":material/refresh:")
        if notice := st.session_state.pop("board_notice", None):
            st.success(notice)
        with st.expander("提醒设置", icon=":material/tune:"):
            threshold = st.number_input("演示超时阈值（小时，从本地任务创建时起计算）", min_value=1, max_value=720, value=24)
            st.caption("该阈值仅用于演示提醒，不是业务承诺；已解决和已关闭任务不计为当前超时。修改阈值不更改任务记录。")
        tasks = board_store.tasks()
        with st.container(horizontal=True):
            st.metric("已确认任务", len(tasks), border=True, icon=":material/task_alt:")
            st.metric("未解决", sum(t["status"] in {"待处理", "处理中"} for t in tasks), border=True, icon=":material/pending_actions:")
            st.metric("P0 未解决", sum(json.loads(t["payload"])["risk"]["level"] == "P0" and t["status"] in {"待处理", "处理中"} for t in tasks), border=True, icon=":material/priority_high:")
            st.metric("当前超时", sum(overdue(t, threshold) for t in tasks), border=True, icon=":material/schedule:")
        status_filter = st.selectbox("筛选状态", ["全部", *TRANSITIONS], key="board_filter")
        rows = [t for t in tasks if status_filter == "全部" or t["status"] == status_filter]
        if not rows:
            st.info("当前没有符合条件的任务。请先在客服工作台展开人工审核并确认一个案例，或调整筛选条件。")
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
                st.caption(f"审核 #{current['review_id']} · 记录截至：{payload['cutoff']}")
                st.text(payload["edited"])
                st.json(payload["risk"], expanded=False)
                try:
                    detail = provider.get_case(picked, payload["cutoff"])
                    for message in detail["messages"]:
                        st.text(f"{message['message_id']} · {message['角色']}\n{message['message_text']}")
                    st.write("关联订单")
                    st.dataframe(detail["orders"], hide_index=True)
                    st.write("截至记录时间的工单")
                    st.dataframe(detail["tickets"], hide_index=True)
                except ValueError:
                    st.warning("当前数据源无法找到原案例；已保存的审核和风险证据仍可查看。")
            with st.form(f"task_update_{picked}_{current['updated']}"):
                assigned = st.text_input("分派负责人", key="board_owner")
                next_status = st.selectbox("更新为", TRANSITIONS[current["status"]], key="board_status")
                actor = st.text_input("本次操作人", key="board_actor")
                note = st.text_area("处理说明／解决结果（必填）", key="board_note")
                confirm_task = st.checkbox("确认本次分派和状态变更", key="board_confirm")
                update = st.form_submit_button("保存任务变更", key="board_save", type="primary", icon=":material/save:")
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
