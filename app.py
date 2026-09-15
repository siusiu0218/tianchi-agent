from pathlib import Path
import os
from html import escape

from dotenv import load_dotenv
import streamlit as st

from copilot.agent import run_case
from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.llm import ModelConfig, generate_draft, model_context

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
    selected = st.selectbox("会话编号", sessions, index=sessions.index("S00268") if "S00268" in sessions else 0)
    messages = provider.messages(selected)
    default = next((i + 1 for i, m in enumerate(messages) if m["角色"] == "买家"), 1)
    position = st.select_slider("回放到第几条消息", options=list(range(1, len(messages) + 1)), value=default, key=f"position_{selected}")
    cutoff = messages[position - 1]["发送时间"]
    st.caption(f"回放时点：{cutoff}")
    st.info("先看 S00268 第一条消息，再拖动回放进度观察证据变化。")

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
        st.dataframe(case["orders"], use_container_width=True, hide_index=True)
    else:
        st.info("暂未查询到此时点的关联订单。")
    st.subheader("回放时点的工单")
    if case["tickets"]:
        st.dataframe(case["tickets"], use_container_width=True, hide_index=True)
    else:
        st.info("按表中创建时间，此时点暂未查询到已创建工单。")
    st.caption(case["time_notice"])
    with st.expander("查看工单数据快照（不参与本次分析）"):
        st.caption("这是工作簿保存的状态，不代表回放时点的状态；它可能与聊天中的说法存在时间差。")
        snapshot = provider.ticket_snapshot(selected)
        if snapshot:
            st.dataframe(snapshot, use_container_width=True, hide_index=True)
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
