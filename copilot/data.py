# 负责读取聊天、订单和工单


from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "赛题 1：数据共情者-业务数据.xlsx"
CHAT_FIELDS = ["message_id", "发送时间", "角色", "message_text", "内容类型", "image_path"]
ORDER_FIELDS = ["订单号", "商品名称", "商品货号", "数量", "下单时间"]
TICKET_FIELDS = ["工单号", "关联订单号", "创建时间"]


class CaseProvider(Protocol):
    def get_case(self, session_id: str, cutoff: str | None = None) -> dict: ...


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ExcelProvider:
    """只读适配器；业务 ID 始终保留为字符串。"""

    def __init__(self, source: Path = DEFAULT_SOURCE):
        self.source = Path(source)
        self.frames = pd.read_excel(source, sheet_name=None, dtype=str, keep_default_na=False)
        for sheet, columns in {"聊天记录": ["会话ID", *CHAT_FIELDS],
                               "订单": ["会话ID", *ORDER_FIELDS]}.items():
            if sheet not in self.frames or not set(columns) <= set(self.frames[sheet].columns):
                raise ValueError(f"数据缺少必要工作表或字段：{sheet}")
        self.ticket_sheets = [name for name in self.frames if name.endswith("工单")]
        for sheet in self.ticket_sheets:
            if not {"会话ID", *TICKET_FIELDS} <= set(self.frames[sheet].columns):
                raise ValueError(f"工单缺少必要字段：{sheet}")

    def sessions(self) -> list[str]:
        return sorted(self.frames["聊天记录"]["会话ID"].unique().tolist())

    def messages(self, session_id: str) -> list[dict]:
        frame = self.frames["聊天记录"]
        rows = frame.loc[frame["会话ID"].eq(session_id), CHAT_FIELDS].to_dict("records")
        return sorted(rows, key=lambda row: parse_time(row["发送时间"]))

    def get_case(self, session_id: str, cutoff: str | None = None) -> dict:
        messages = self.messages(session_id)
        if not messages:
            raise ValueError("暂未查询到该会话")
        # Default: first buyer message, before subsequent replies and settlements.
        cutoff = cutoff or next((m["发送时间"] for m in messages if m["角色"] == "买家"), messages[0]["发送时间"])
        moment = parse_time(cutoff)
        visible = [m for m in messages if parse_time(m["发送时间"]) <= moment]
        orders, tickets = [], []
        frame = self.frames["订单"]
        for row in frame.loc[frame["会话ID"].eq(session_id)].to_dict("records"):
            if row["下单时间"] and parse_time(row["下单时间"]) <= moment:
                orders.append({key: row[key] for key in ORDER_FIELDS})
        for sheet in self.ticket_sheets:
            frame = self.frames[sheet]
            for row in frame.loc[frame["会话ID"].eq(session_id)].to_dict("records"):
                if row["创建时间"] and parse_time(row["创建时间"]) <= moment:
                    tickets.append({"工单类别": sheet, **{key: row[key] for key in TICKET_FIELDS}})
        # Mutable snapshot fields have no history; never reconstruct past status from them.
        return {"session_id": session_id, "cutoff": cutoff, "messages": visible,
                "orders": orders, "tickets": tickets,
                "image_notice": "图片未参与识别；本版仅处理文字。",
                "time_notice": "仅展示回放时点前的记录；订单购买字段视为固定事实。当前状态、症状登记与处理结果没有变更历史，不用于历史回放。"}

    def ticket_snapshot(self, session_id: str) -> list[dict]:
        """Display-only final workbook snapshot, never passed to the agent."""
        rows = []
        fields = ["工单号", "关联订单号", "创建时间", "任务状态", "完成时间"]
        for sheet in self.ticket_sheets:
            frame = self.frames[sheet]
            for row in frame.loc[frame["会话ID"].eq(session_id)].to_dict("records"):
                rows.append({"工单类别": sheet, **{key: row.get(key, "") for key in fields}})
        return rows
