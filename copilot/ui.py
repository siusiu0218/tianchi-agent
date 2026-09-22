"""Presentation helpers for the inbox. No business actions or model calls."""
from html import escape

import streamlit as st


STYLE = """
<style>
/* Scope layout rules to this workbench; retain native accessible controls. */
[data-testid="stHeader"] {background:transparent; height:2.2rem;}
[data-testid="stAppDeployButton"] {display:none;}
[data-testid="stMainBlockContainer"] {padding:1.3rem 1.4rem 2rem; max-width:none;}
[data-testid="stSidebar"] {min-width:184px!important; max-width:184px!important; border-right:1px solid #e8ebf0;}
[data-testid="stSidebarContent"] {padding:0;}
[data-testid="stSidebarUserContent"] {padding:1.3rem .75rem; width:100%;}
.st-key-workspace_tabs > div > [role="tablist"] {display:none;}
.st-key-workspace_tabs [data-testid="stTabs"] {gap:0;}
.st-key-inbox_grid {gap:0!important;}
.st-key-inbox_grid [data-testid="stHorizontalBlock"] {gap:0!important; align-items:stretch;}
.st-key-inbox_grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {padding:0 1rem; border-right:1px solid #e8ebf0; min-width:0;}
.st-key-inbox_grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {padding-left:0;}
.st-key-inbox_grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {border:0; padding-right:0;}
.brand {display:flex; gap:9px; align-items:center; white-space:nowrap; font-size:17px; font-weight:650; padding:3px 0 26px; color:#202735;}
.brand-mark {background:#3375ed; color:white; width:27px; height:27px; border-radius:9px; display:grid; place-items:center; font-size:18px;}
.nav-label {font-size:11px; color:#929aaa; letter-spacing:.1em; margin:22px 0 10px;}
.sidebar-note {font-size:12px; color:#8992a2; line-height:1.8; margin-top:22px;}
[data-testid="stSidebar"] button {text-align:left; justify-content:flex-start;}
.st-key-session_list {gap:4px;}
.st-key-inbox_grid [data-testid="stLayoutWrapper"]:has(> .st-key-session_list),
.st-key-inbox_grid [data-testid="stLayoutWrapper"]:has(> .st-key-chat_feed) {height:auto!important; flex:0 0 auto!important;}
.st-key-session_list button {border:0; border-radius:8px; min-height:77px; padding:10px 12px; text-align:left; justify-content:flex-start; background:transparent;}
.st-key-session_list button p {white-space:pre-line; font-size:12px; line-height:1.7; color:#778194;}
.st-key-session_list button [data-testid="stMarkdownContainer"] {width:100%; text-align:left;}
.st-key-session_list button > div {width:100%; text-align:left; align-items:flex-start; justify-content:flex-start;}
.st-key-session_list button > div > span {flex:1 1 0%; width:100%; min-width:0; text-align:left; justify-content:flex-start;}
.st-key-session_list button strong {font-size:14px; color:#293344; font-weight:600;}
.st-key-session_list button[kind="primary"] {background:#edf4ff; border-left:3px solid #3478f6;}
.st-key-session_list button:hover {background:#f4f7fb;}
.st-key-session_list button[kind="primary"] p {color:#4a73a9;}
.conversation-head {display:flex; gap:10px; align-items:center; padding:1px 0 14px; border-bottom:1px solid #edf0f4; margin-bottom:5px;}
.avatar {background:#e8effc; color:#4470b0; width:37px; height:37px; border-radius:50%; display:grid; place-items:center; font-size:13px; font-weight:600; flex-shrink:0;}
.conversation-head strong {font-size:15px; font-weight:600; color:#283243;}
.meta {font-size:11px; color:#8b94a4; margin-top:3px;}
.status-tag {margin-left:auto; color:#69768a; background:#f2f4f7; font-size:11px; padding:4px 9px; border-radius:6px;}
.st-key-chat_feed {background:#fcfcfd; border-radius:4px; height:370px!important; flex:0 0 auto!important; overflow-y:auto;}
.st-key-chat_feed [data-testid="stChatMessage"] {background:transparent; padding:8px 2px; gap:8px;}
.st-key-chat_feed [data-testid="stChatMessage"]:has(.outgoing) {flex-direction:row-reverse;}
.st-key-chat_feed [data-testid="stChatMessage"]:has(.outgoing) [data-testid="stChatMessageContent"] {display:flex; justify-content:flex-end;}
.st-key-chat_feed [data-testid="stChatMessageAvatarUser"], .st-key-chat_feed [data-testid="stChatMessageAvatarAssistant"] {width:26px; height:26px; background:#e7edf6; color:#68778f;}
.bubble {border-radius:3px 13px 13px 13px; background:#edf0f4; padding:12px 14px; max-width:95%; font-size:14px; line-height:1.75; color:#303b4c; overflow-wrap:anywhere; white-space:pre-wrap;}
.bubble.outgoing {background:#e2efff; border-radius:13px 3px 13px 13px;}
.chat-date {text-align:center; color:#8b94a4; font-size:11px; margin:10px 0;}
.bubble-time {font-size:10px; color:#8290a2; display:block; margin-top:6px;}
.st-key-composer {border:1px solid #e5e9f0; border-radius:10px; padding:12px;}
.st-key-composer textarea {background:white; border:0; font-size:13px; line-height:1.75;}
.st-key-composer [data-testid="stTextArea"] > div {border:0; box-shadow:none;}
.section-label {font-size:12px; font-weight:600; color:#7b8798; margin:12px 0 8px;}
.profile {text-align:center; padding:12px 0 16px;}
.profile .avatar {margin:0 auto 9px; width:48px; height:48px; font-size:17px;}
.profile strong {font-size:15px;}
.fact {padding:10px 0; border-bottom:1px solid #f0f2f5; font-size:12px; color:#566276; overflow-wrap:anywhere;}
.fact small {display:block; font-size:11px; color:#929aaa; margin-bottom:5px;}
.risk-note {padding:11px 12px; border-radius:8px; font-size:12px; line-height:1.7; background:#fff4ed; color:#98512b; border:1px solid #f9e4d7;}
.risk-note.high {background:#fff0f0; border-color:#f8dedf; color:#a34449;}
.st-key-inspector [data-testid="stAlert"] {font-size:12px;}
.st-key-inspector [data-testid="stExpander"] {border-color:#e9ecf2; background:#fafbfc;}
.st-key-inspector [data-testid="stExpander"] summary p {font-size:12px;}
.st-key-inspector [data-testid="stCaptionContainer"] p {font-size:11px;}
@media(min-width:1100px) {
 .st-key-chat_feed {height:calc(100vh - 355px)!important; min-height:270px; max-height:630px;}
 .st-key-session_list {height:calc(100vh - 220px)!important; min-height:380px;}
}
@media(max-width:1099px) {
 [data-testid="stMainBlockContainer"] {padding:1.2rem .8rem;}
 .st-key-inbox_grid [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
 .st-key-inbox_grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:250px; padding:.7rem;}
}
@media(max-width:640px) {
 .st-key-inbox_grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:100%; border-right:0;}
 .st-key-session_list {max-height:205px;}
}
</style>
"""


def apply_style():
    st.html(STYLE)


def conversation_header(session):
    st.html(f'<div class="conversation-head"><span class="avatar">客</span><div><strong>客户 · {escape(session)}</strong><div class="meta">在线咨询 · 聊天记录</div></div><span class="status-tag">人工处理</span></div>')


def bubble(message):
    outgoing = message["角色"] != "买家"
    kind = " outgoing" if outgoing else ""
    # Untrusted workbook text is always escaped before HTML rendering.
    st.html(f'<div class="bubble{kind}">{escape(message["message_text"])}<span class="bubble-time">{escape(message["角色"])} · {escape(message["发送时间"])} </span></div>')


def fact(label, value):
    st.html(f'<div class="fact"><small>{escape(label)}</small>{escape(str(value))}</div>')
