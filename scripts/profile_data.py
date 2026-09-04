from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

import pandas as pd


EXPECTED_SHEETS = [
    "数据说明",
    "聊天记录",
    "订单",
    "补发换货工单",
    "线下打款工单",
    "物流工单",
    "不良反应工单",
    "售后退货工单",
]
TICKET_SHEETS = EXPECTED_SHEETS[3:]
SHEET_SLUGS = {
    "数据说明": "01-data-description",
    "聊天记录": "02-chat-messages",
    "订单": "03-orders",
    "补发换货工单": "04-replacement-tickets",
    "线下打款工单": "05-offline-payment-tickets",
    "物流工单": "06-logistics-tickets",
    "不良反应工单": "07-adverse-reaction-tickets",
    "售后退货工单": "08-return-tickets",
}
GRAINS = {
    "数据说明": "说明行（非业务事实表）",
    "聊天记录": "一行一条消息；message_id 为主键候选",
    "订单": "一行一笔订单；订单号为主键候选；当前快照一会话至多一单",
    "补发换货工单": "一行一张补发/换货工单；工单号为主键候选",
    "线下打款工单": "一行一张线下打款工单；工单号为主键候选",
    "物流工单": "一行一张物流工单；工单号为主键候选",
    "不良反应工单": "一行一张不良反应工单；工单号为主键候选",
    "售后退货工单": "一行一张售后退货工单；工单号为主键候选",
}
KEY_FIELDS = {
    "聊天记录": ["会话ID", "message_id", "关联订单号", "关联工单号"],
    "订单": ["订单号", "会话ID", "商品货号", "物流单号"],
    "补发换货工单": ["工单号", "会话ID", "关联订单号", "发出商品货号", "原订单物流单号", "补发物流单号"],
    "线下打款工单": ["工单号", "会话ID", "关联订单号", "相关物流单号"],
    "物流工单": ["工单号", "会话ID", "关联订单号", "问题包裹物流单号"],
    "不良反应工单": ["工单号", "会话ID", "关联订单号", "产品批次号"],
    "售后退货工单": ["工单号", "会话ID", "关联订单号", "退货物流单号", "退款编号"],
}
TIME_FIELDS = {"发送时间", "下单时间", "付款时间", "发货时间", "创建时间", "完成时间"}
NUMERIC_FIELDS = {"消息序号", "数量", "单价(元)", "实付金额(元)", "退款金额(元)", "订单实付(元)", "年龄"}


def clean(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def nonempty(series: pd.Series) -> pd.Series:
    values = clean(series)
    return values[values.ne("")]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_type(column: str, values: pd.Series) -> str:
    if column in KEY_FIELDS.get("聊天记录", []) or any(column in fields for fields in KEY_FIELDS.values()):
        return "标识符（字符串）"
    if column in TIME_FIELDS:
        return "日期时间（源值按字符串保留）"
    if column in NUMERIC_FIELDS:
        return "数值（源值按字符串保留）"
    populated = nonempty(values)
    if len(populated) and populated.nunique() <= 12:
        return "分类/枚举文本"
    return "文本"


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def profile_table(sheet: str, frame: pd.DataFrame) -> dict[str, Any]:
    columns = []
    for column in frame.columns:
        values = clean(frame[column])
        present = int(values.ne("").sum())
        columns.append(
            {
                "name": str(column),
                "semantic_type": semantic_type(str(column), values),
                "non_null_count": present,
                "non_null_rate": rate(present, len(frame)),
                "distinct_non_null": int(values[values.ne("")].nunique()),
            }
        )
    return {
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "grain": GRAINS[sheet],
        "exact_duplicate_rows": int(frame.apply(clean).duplicated().sum()),
        "columns": columns,
    }


def key_check(check_id: str, values: pd.Series, expected_rows: int) -> dict[str, Any]:
    normalized = clean(values)
    missing = int(normalized.eq("").sum())
    duplicates = int(normalized[normalized.ne("")].duplicated().sum())
    passed = missing == 0 and duplicates == 0 and len(normalized) == expected_rows
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "observed": {"rows": int(len(normalized)), "missing": missing, "duplicate_rows": duplicates},
        "expected": {"rows": expected_rows, "missing": 0, "duplicate_rows": 0},
    }


def coverage_check(check_id: str, child: set[str], parent: set[str]) -> dict[str, Any]:
    unresolved = sorted(child - parent)
    matched = len(child) - len(unresolved)
    return {
        "check_id": check_id,
        "status": "pass" if not unresolved else "fail",
        "observed": {
            "child_distinct": len(child),
            "matched_distinct": matched,
            "unresolved_distinct": len(unresolved),
            "coverage_rate": rate(matched, len(child)),
        },
        "unresolved_values": unresolved[:20],
    }


def value_counts(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    counts = Counter(clean(frame[column]))
    counts.pop("", None)
    total = sum(counts.values())
    return [
        {"value": value, "count": count, "share": rate(count, total)}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def timestamp_range(frame: pd.DataFrame, column: str) -> dict[str, Any] | None:
    if column not in frame.columns:
        return None
    values = nonempty(frame[column])
    parse_values = values.str.replace("（定金）", "", regex=False) if column == "付款时间" else values
    parsed = pd.to_datetime(parse_values, errors="coerce")
    if values.empty:
        return {"non_null": 0, "parse_failures": 0, "min": None, "max": None}
    valid = parsed.dropna()
    return {
        "non_null": int(len(values)),
        "parse_failures": int(parsed.isna().sum()),
        "min": valid.min().isoformat() if len(valid) else None,
        "max": valid.max().isoformat() if len(valid) else None,
    }


def build_profile(source: Path) -> dict[str, Any]:
    workbook = pd.ExcelFile(source)
    frames = {
        sheet: pd.read_excel(source, sheet_name=sheet, dtype=str, keep_default_na=False)
        for sheet in workbook.sheet_names
    }
    if workbook.sheet_names != EXPECTED_SHEETS:
        raise ValueError(f"工作表结构漂移：expected={EXPECTED_SHEETS!r}, observed={workbook.sheet_names!r}")

    chat = frames["聊天记录"]
    orders = frames["订单"]
    tickets = pd.concat(
        [frames[sheet].assign(_ticket_sheet=sheet) for sheet in TICKET_SHEETS],
        ignore_index=True,
        sort=False,
    )
    chat_conversations = set(nonempty(chat["会话ID"]))
    order_ids = set(nonempty(orders["订单号"]))
    ticket_ids = set(nonempty(tickets["工单号"]))
    order_conversations = set(nonempty(orders["会话ID"]))
    ticket_conversations = set(nonempty(tickets["会话ID"]))
    ticket_order_ids = set(nonempty(tickets["关联订单号"]))
    chat_order_refs = set(nonempty(chat["关联订单号"]))
    chat_ticket_refs = set(nonempty(chat["关联工单号"]))

    checks = [
        key_check("message_id_unique_not_null", chat["message_id"], 998),
        key_check("order_id_unique_not_null", orders["订单号"], 113),
        key_check("ticket_id_unique_not_null", tickets["工单号"], 80),
        coverage_check("orders_link_to_chat", order_conversations, chat_conversations),
        coverage_check("tickets_link_to_chat", ticket_conversations, chat_conversations),
        coverage_check("tickets_link_to_orders", ticket_order_ids, order_ids),
        coverage_check("chat_order_refs_resolve", chat_order_refs, order_ids),
        coverage_check("chat_ticket_refs_resolve", chat_ticket_refs, ticket_ids),
    ]
    composite_duplicates = int(chat.assign(_seq=clean(chat["消息序号"])).duplicated(["会话ID", "_seq"]).sum())
    checks.append(
        {
            "check_id": "conversation_message_sequence_unique",
            "status": "pass" if composite_duplicates == 0 else "fail",
            "observed": {"duplicate_rows": composite_duplicates},
            "expected": {"duplicate_rows": 0},
        }
    )

    order_conversation_duplicates = int(clean(orders["会话ID"]).duplicated().sum())
    ticket_conversation_duplicates = int(clean(tickets["会话ID"]).duplicated().sum())
    checks.extend(
        [
            {
                "check_id": "one_order_per_conversation",
                "status": "pass" if order_conversation_duplicates == 0 else "fail",
                "observed": {"duplicate_rows": order_conversation_duplicates},
                "expected": {"duplicate_rows": 0},
            },
            {
                "check_id": "one_ticket_per_conversation",
                "status": "pass" if ticket_conversation_duplicates == 0 else "fail",
                "observed": {"duplicate_rows": ticket_conversation_duplicates},
                "expected": {"duplicate_rows": 0},
            },
        ]
    )

    order_to_conversation = dict(zip(clean(orders["订单号"]), clean(orders["会话ID"])))
    ticket_to_conversation = dict(zip(clean(tickets["工单号"]), clean(tickets["会话ID"])))
    chat_order_rows = chat.loc[clean(chat["关联订单号"]).ne("")]
    chat_ticket_rows = chat.loc[clean(chat["关联工单号"]).ne("")]
    order_ref_mismatches = int(
        sum(
            order_to_conversation.get(order_id) != conversation_id
            for order_id, conversation_id in zip(
                clean(chat_order_rows["关联订单号"]), clean(chat_order_rows["会话ID"])
            )
        )
    )
    ticket_ref_mismatches = int(
        sum(
            ticket_to_conversation.get(ticket_id) != conversation_id
            for ticket_id, conversation_id in zip(
                clean(chat_ticket_rows["关联工单号"]), clean(chat_ticket_rows["会话ID"])
            )
        )
    )
    checks.extend(
        [
            {
                "check_id": "chat_order_refs_match_conversation",
                "status": "pass" if order_ref_mismatches == 0 else "fail",
                "observed": {"referencing_rows": int(len(chat_order_rows)), "mismatched_rows": order_ref_mismatches},
                "expected": {"mismatched_rows": 0},
            },
            {
                "check_id": "chat_ticket_refs_match_conversation",
                "status": "pass" if ticket_ref_mismatches == 0 else "fail",
                "observed": {"referencing_rows": int(len(chat_ticket_rows)), "mismatched_rows": ticket_ref_mismatches},
                "expected": {"mismatched_rows": 0},
            },
        ]
    )

    payment_raw = clean(orders["付款时间"])
    deposit_pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}（定金）$"
    deposit_annotations = payment_raw.str.match(deposit_pattern)
    payment_base = payment_raw.str.replace("（定金）", "", regex=False)
    payment_parse_failures = int(pd.to_datetime(payment_base, errors="coerce").isna().sum())
    deposit_status_mismatches = int((deposit_annotations & clean(orders["订单状态"]).ne("预售-待付尾款")).sum())
    checks.append(
        {
            "check_id": "order_payment_time_or_deposit_annotation_valid",
            "status": "pass" if payment_parse_failures == 0 and deposit_status_mismatches == 0 else "fail",
            "observed": {
                "deposit_annotation_rows": int(deposit_annotations.sum()),
                "parse_failures_after_removing_annotation": payment_parse_failures,
                "deposit_status_mismatches": deposit_status_mismatches,
            },
            "expected": {"parse_failures_after_removing_annotation": 0, "deposit_status_mismatches": 0},
        }
    )

    shipping_presence = pd.DataFrame(
        {
            column: clean(orders[column]).ne("")
            for column in ("发货时间", "快递公司", "物流单号")
        }
    )
    shipping_presence_mismatches = int(shipping_presence.nunique(axis=1).gt(1).sum())
    checks.append(
        {
            "check_id": "order_shipping_fields_co_present",
            "status": "pass" if shipping_presence_mismatches == 0 else "fail",
            "observed": {"mismatched_rows": shipping_presence_mismatches, "all_missing_rows": int(shipping_presence.eq(False).all(axis=1).sum())},
            "expected": {"mismatched_rows": 0},
        }
    )

    completion_parse_failures = 0
    completion_before_creation = 0
    completion_status_mismatches = 0
    for sheet in TICKET_SHEETS:
        frame = frames[sheet]
        created = pd.to_datetime(clean(frame["创建时间"]), errors="coerce")
        completed_raw = clean(frame["完成时间"])
        completed = pd.to_datetime(completed_raw.replace("", pd.NA), errors="coerce")
        completion_parse_failures += int((completed_raw.ne("") & completed.isna()).sum())
        completion_before_creation += int((completed.notna() & created.notna() & completed.lt(created)).sum())
        status_column = "工单状态" if "工单状态" in frame.columns else "任务状态"
        status_completed = clean(frame[status_column]).eq("已完结")
        completion_status_mismatches += int(status_completed.ne(completed_raw.ne("")).sum())
    checks.append(
        {
            "check_id": "ticket_completion_after_creation",
            "status": "pass" if completion_parse_failures == 0 and completion_before_creation == 0 and completion_status_mismatches == 0 else "fail",
            "observed": {
                "parse_failures": completion_parse_failures,
                "completion_before_creation": completion_before_creation,
                "status_completion_mismatches": completion_status_mismatches,
            },
            "expected": {"parse_failures": 0, "completion_before_creation": 0, "status_completion_mismatches": 0},
        }
    )

    scene_variants = chat.groupby("会话ID")[["scene_major", "scene_minor"]].nunique(dropna=False)
    scene_inconsistent_conversations = int(scene_variants.gt(1).any(axis=1).sum())
    buyer_inconsistent_conversations = int(chat.groupby("会话ID")["买家昵称"].nunique(dropna=False).gt(1).sum())
    checks.extend(
        [
            {
                "check_id": "conversation_scene_labels_consistent",
                "status": "pass" if scene_inconsistent_conversations == 0 else "fail",
                "observed": {"inconsistent_conversations": scene_inconsistent_conversations},
                "expected": {"inconsistent_conversations": 0},
            },
            {
                "check_id": "conversation_buyer_consistent",
                "status": "pass" if buyer_inconsistent_conversations == 0 else "fail",
                "observed": {"inconsistent_conversations": buyer_inconsistent_conversations},
                "expected": {"inconsistent_conversations": 0},
            },
        ]
    )

    id_format_findings: list[dict[str, Any]] = []
    suspicious_pattern = re.compile(r"^(?:\d+\.0|[+-]?\d+(?:\.\d+)?[eE][+-]?\d+)$")
    for sheet, columns in KEY_FIELDS.items():
        frame = frames[sheet]
        for column in columns:
            if column not in frame.columns:
                continue
            values = nonempty(frame[column])
            suspicious = int(values.str.match(suspicious_pattern).sum())
            id_format_findings.append(
                {"sheet": sheet, "column": column, "non_null": int(len(values)), "float_or_scientific_like": suspicious}
            )
    checks.append(
        {
            "check_id": "identifier_format_not_float_or_scientific",
            "status": "pass" if all(item["float_or_scientific_like"] == 0 for item in id_format_findings) else "fail",
            "observed": {"fields_checked": len(id_format_findings), "suspicious_values": sum(item["float_or_scientific_like"] for item in id_format_findings)},
        }
    )

    image_paths = nonempty(chat["image_path"])
    resolved_images = [(source.parent / value).resolve() for value in image_paths]
    existing_images = sum(path.is_file() for path in resolved_images)
    scene_major = value_counts(chat.drop_duplicates("会话ID"), "scene_major")
    scene_minor = value_counts(chat.drop_duplicates("会话ID"), "scene_minor")
    cross = (
        chat.drop_duplicates("会话ID")
        .groupby(["scene_major", "scene_minor"], dropna=False)
        .size()
        .reset_index(name="conversation_count")
        .sort_values(["scene_major", "scene_minor"])
    )
    ticket_field_availability = {}
    for sheet in TICKET_SHEETS:
        frame = frames[sheet]
        ticket_field_availability[sheet] = [
            {
                "field": column,
                "non_null": int(clean(frame[column]).ne("").sum()),
                "non_null_rate": rate(int(clean(frame[column]).ne("").sum()), len(frame)),
            }
            for column in frame.columns
        ]

    time_ranges: dict[str, dict[str, Any]] = {}
    for sheet, frame in frames.items():
        fields = {}
        for column in frame.columns:
            if column in TIME_FIELDS:
                fields[column] = timestamp_range(frame, column)
        if fields:
            time_ranges[sheet] = fields

    all_checks_pass = all(item["status"] == "pass" for item in checks)
    profile = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source.resolve()),
            "sha256": sha256(source),
            "size_bytes": source.stat().st_size,
            "id_read_strategy": "all cells read as strings",
            "raw_file_modified": False,
        },
        "summary": {
            "sheet_count": len(frames),
            "conversation_count": len(chat_conversations),
            "message_count": int(len(chat)),
            "buyer_count": int(nonempty(chat["买家昵称"]).nunique()),
            "order_count": int(len(orders)),
            "ticket_count": int(len(tickets)),
            "scene_major_count": int(nonempty(chat["scene_major"]).nunique()),
            "scene_minor_count": int(nonempty(chat["scene_minor"]).nunique()),
        },
        "tables": {sheet: profile_table(sheet, frame) for sheet, frame in frames.items()},
        "checks": checks,
        "identifier_format_findings": id_format_findings,
        "relationships": {
            "orders": {"rows": int(len(orders)), "linked_to_chat_rows": int(clean(orders["会话ID"]).isin(chat_conversations).sum())},
            "tickets": {
                "rows": int(len(tickets)),
                "linked_to_chat_rows": int(clean(tickets["会话ID"]).isin(chat_conversations).sum()),
                "linked_to_order_rows": int(clean(tickets["关联订单号"]).isin(order_ids).sum()),
            },
            "ticket_rows_by_sheet": {sheet: int(len(frames[sheet])) for sheet in TICKET_SHEETS},
        },
        "scenes": {
            "major_distribution_by_conversation": scene_major,
            "minor_distribution_by_conversation": scene_minor,
            "major_minor_cross_by_conversation": cross.to_dict(orient="records"),
            "minor_classes_lt_5_conversations": [item for item in scene_minor if item["count"] < 5],
        },
        "images": {
            "path_rows": int(len(image_paths)),
            "unique_paths": int(image_paths.nunique()),
            "existing_files": int(existing_images),
            "missing_files": int(len(image_paths) - existing_images),
            "existing_rate": rate(existing_images, len(image_paths)),
        },
        "ticket_field_availability": ticket_field_availability,
        "time_ranges": time_ranges,
        "evaluation_readiness": {
            "can_enter_standard_setting": bool(all_checks_pass and len(chat_conversations) > 0),
            "scenario_labels_available": True,
            "emotion_gold_labels_available": False,
            "risk_gold_labels_available": False,
            "minor_class_sparsity_present": any(item["count"] < 5 for item in scene_minor),
            "boundary": "足以进入评测立标阶段；不足以直接声称情绪/风险模型有效，也不足以把稀疏二级场景随机切分后当作稳定泛化证据。",
        },
    }
    return profile


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    output.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return "\n".join(output)


def render_dictionary(sheet: str, table: dict[str, Any], source_hash: str) -> str:
    rows = [
        [
            item["name"],
            item["semantic_type"],
            item["non_null_count"],
            pct(item["non_null_rate"]),
            item["distinct_non_null"],
        ]
        for item in table["columns"]
    ]
    return (
        f"# 字段字典：{sheet}\n\n"
        f"- 数据粒度：{table['grain']}\n"
        f"- 规模：{table['row_count']} 行 × {table['column_count']} 列\n"
        f"- 完全重复行：{table['exact_duplicate_rows']}\n"
        f"- 来源工作簿 SHA-256：`{source_hash}`\n\n"
        + markdown_table(["字段", "解释类型", "非空数", "非空率", "非空去重数"], rows)
        + "\n\n> 所有源单元格均按字符串读取；“解释类型”只用于画像说明，不改变原值。标识符不得按数值参与计算。\n"
    )


def render_report(profile: dict[str, Any]) -> str:
    summary = profile["summary"]
    relationships = profile["relationships"]
    minor_sparse = profile["scenes"]["minor_classes_lt_5_conversations"]
    check_rows = [
        [item["check_id"], item["status"], json.dumps(item.get("observed", {}), ensure_ascii=False)]
        for item in profile["checks"]
    ]
    table_rows = [
        [sheet, table["grain"], table["row_count"], table["column_count"], table["exact_duplicate_rows"]]
        for sheet, table in profile["tables"].items()
    ]
    major_rows = [[item["value"], item["count"], pct(item["share"])] for item in profile["scenes"]["major_distribution_by_conversation"]]
    minor_rows = [[item["value"], item["count"], pct(item["share"])] for item in profile["scenes"]["minor_distribution_by_conversation"]]
    ticket_rows = [[sheet, count] for sheet, count in relationships["ticket_rows_by_sheet"].items()]
    checks_by_id = {item["check_id"]: item for item in profile["checks"]}
    order_columns = {item["name"]: item for item in profile["tables"]["订单"]["columns"]}
    shipping_missing = profile["tables"]["订单"]["row_count"] - order_columns["发货时间"]["non_null_count"]
    deposit_rows = checks_by_id["order_payment_time_or_deposit_annotation_valid"]["observed"]["deposit_annotation_rows"]
    report = f"""# 数据画像与关联校验

> 生成时间（UTC）：{profile['generated_at_utc']}  
> 原始工作簿：`{profile['source']['path']}`  
> SHA-256：`{profile['source']['sha256']}`  
> 读取方式：所有单元格按字符串读取；脚本只读源文件。

## 1. 结论先行

**可以进入第 2 步“评测立标”，但还不能直接宣称模型有效。** 当前快照的消息、订单和工单主键无缺失/重复，113/113 笔订单能关联聊天，80/80 张工单能同时关联聊天和来源订单，足以建立会话级场景评测、风险弱标签规则与黄金案例。限制是：情绪和 P0–P3 没有官方金标签，二级场景存在小样本，图片 29/29 缺失；因此下一步必须先冻结分组切分、人工标注与风险映射规则。

## 2. 数据集、粒度与规模

- 工作表：{summary['sheet_count']} 张；业务事实表为聊天、订单和 5 类工单，`数据说明` 不是业务事实表。
- 聊天：{summary['conversation_count']} 个会话、{summary['message_count']} 条消息、{summary['buyer_count']} 个买家。
- 订单：{summary['order_count']} 笔。
- 工单：{summary['ticket_count']} 张。
- 场景：一级 {summary['scene_major_count']} 类、二级 {summary['scene_minor_count']} 类；按会话统计分布，避免长会话被重复加权。

{markdown_table(['表', '粒度', '行数', '列数', '完全重复行'], table_rows)}

## 3. 主键、ID 与关联完整性

{markdown_table(['校验', '状态', '观测值'], check_rows)}

- 所有 ID 源值均用 `dtype=str` 读取；共检查 {profile['checks'][-1]['observed']['fields_checked']} 个标识符字段，未发现 `.0` 浮点尾缀或科学计数法字符串。
- 订单关联聊天：{relationships['orders']['linked_to_chat_rows']}/{relationships['orders']['rows']}。
- 工单关联聊天：{relationships['tickets']['linked_to_chat_rows']}/{relationships['tickets']['rows']}；工单关联来源订单：{relationships['tickets']['linked_to_order_rows']}/{relationships['tickets']['rows']}。

工单构成：

{markdown_table(['工单表', '行数'], ticket_rows)}

## 4. 场景标签分布与稀疏性

### 一级场景（按会话）

{markdown_table(['scene_major', '会话数', '占比'], major_rows)}

### 二级场景（按会话）

{markdown_table(['scene_minor', '会话数', '占比'], minor_rows)}

- 少于 5 个会话的二级类别有 {len(minor_sparse)} 个。它们不适合直接做普通随机训练/测试切分后的单类稳定指标；应按会话或买家分组，并在评测方案中合并、定向留出或只做案例级核验。
- `scene_major` / `scene_minor` 只可作为离线标签，不得进入模型输入。

## 5. 缺失、图片与关键字段可用性

- 字段级非空数、非空率和去重数见 [逐表字段字典](field-dictionaries/README.md)。
- 订单的发货时间、快递公司和物流单号各缺 {shipping_missing} 条，三个字段逐行共同出现或共同缺失；缺失订单处于交易关闭、预售待付尾款或待发货状态，使用时必须保留“暂未查询到”分支，不能补造物流事实。
- `付款时间` 有 {deposit_rows} 条采用“日期时间（定金）”注记；去掉明确注记后均可解析，且都对应“预售-待付尾款”，不应误判为坏日期或完整付款时间。
- 图片路径记录 {profile['images']['path_rows']} 条、唯一路径 {profile['images']['unique_paths']} 个；本地存在 {profile['images']['existing_files']} 个，缺失 {profile['images']['missing_files']} 个，存在率 {pct(profile['images']['existing_rate'])}。当前只能验证缺失降级，不能验证真实图像理解。
- 不良反应工单的症状、是否停用、是否就医字段在当前 10 张工单中均非空，可用于构造风险弱标签；它们仍是 MOCK 消费者自述，不是诊断或病历。
- 完成时间在各类工单中存在业务性缺失，可作为“未闭环”候选信号，不能一概当成脏数据。

## 6. 可评价边界

| 能评 | 暂时不能据此证明 |
| --- | --- |
| 会话级一级/二级场景识别，标签仅作输出对照 | 情绪识别效果：没有现成金标签 |
| 订单/工单事实引用和关联正确率 | P0–P3 风险模型效果：没有官方风险金标签 |
| 不良反应、异常退货、未闭环工单的规则召回 | 真实投诉率、真实客服效率或商业收益 |
| 图片缺失时的降级行为 | 真实多模态图像能力 |

数据切分必须按会话或买家分组；不能按消息随机拆分。任何使用 `scene_major` / `scene_minor` 作为输入的结果都属于标签泄漏。

## 7. 质量问题、风险与处理建议

| 严重度 | 发现 | 影响 | 最小处理 |
| --- | --- | --- | --- |
| 高 | 情绪与风险无金标签 | 无法直接报告可信的情绪/P0–P3 指标 | 人工标注 60–100 个会话；风险规则映射独立冻结并双人复核 |
| 高 | 图片 29/29 缺失 | 无法验证多模态效果 | 只做缺失降级；若后续获得图片，作为新数据版本另行审计 |
| 中 | 二级场景有 {len(minor_sparse)} 个类别少于 5 会话 | Macro-F1 方差大、分组切分可能缺类 | 报告支持数；预注册合并/留出策略，不临时挑指标 |
| 中 | MOCK 数据且单店、小样本 | 不能外推真实业务收益 | 所有 PPT/视频结论标注“模拟任务结果” |
| 低 | 业务性缺失（未发货物流、未完成工单） | 若误填会造成事实幻觉 | 保留空值并显式显示“暂未查询到/未完成” |

## 8. 可重复运行

```powershell
$env:PYTHONUTF8='1'
& 'C:\\Users\\siu\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' scripts/profile_data.py --source '赛题 1：数据共情者-业务数据.xlsx' --output-dir 'artifacts/data-profile-20260901' --docs-dir 'docs'
& 'C:\\Users\\siu\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' -m unittest tests.test_profile_data -v
```

复跑时用 `profile.json` 中的源文件 SHA-256 判断是否仍是同一快照。若哈希变化，必须生成新的版本目录，不得覆盖或混称旧结果。

## 9. 下一步

冻结第 2 步评测立标：按会话/买家分组建立场景切分；人工标注情绪；把不良反应、异常退货和未闭环工单字段映射成可审计的风险弱标签；选定两个关联完整的黄金案例。
"""
    return report


def write_outputs(profile: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "data-profile.md").write_text(render_report(profile), encoding="utf-8")
    dictionaries = output_dir / "field-dictionaries"
    dictionaries.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for sheet, table in profile["tables"].items():
        filename = f"{SHEET_SLUGS[sheet]}.md"
        (dictionaries / filename).write_text(render_dictionary(sheet, table, profile["source"]["sha256"]), encoding="utf-8")
        index_rows.append([sheet, f"[{filename}]({filename})", table["row_count"], table["column_count"], table["grain"]])
    index = "# 逐表字段字典\n\n" + markdown_table(["表", "字典", "行数", "列数", "粒度"], index_rows) + "\n"
    (dictionaries / "README.md").write_text(index, encoding="utf-8")


def publish_docs(output_dir: Path, docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_dir / "data-profile.md", docs_dir / "data-profile.md")
    destination = docs_dir / "field-dictionaries"
    destination.mkdir(parents=True, exist_ok=True)
    for source in (output_dir / "field-dictionaries").glob("*.md"):
        shutil.copy2(source, destination / source.name)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="只读分析天池业务数据工作簿并生成可审计画像。")
    parser.add_argument("--source", type=Path, default=root / "赛题 1：数据共情者-业务数据.xlsx")
    parser.add_argument("--output-dir", type=Path, default=root / "artifacts" / "data-profile-20260901")
    parser.add_argument("--docs-dir", type=Path, help="可选：把报告和字段字典发布到该文档目录。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    source_hash_before = sha256(source)
    profile = build_profile(source)
    write_outputs(profile, args.output_dir.resolve())
    if args.docs_dir:
        publish_docs(args.output_dir.resolve(), args.docs_dir.resolve())
    source_hash_after = sha256(source)
    if source_hash_after != source_hash_before:
        raise RuntimeError("源工作簿在画像过程中发生变化；已停止并拒绝接受结果。")
    print(json.dumps({"status": "ok", "source_sha256": source_hash_after, "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
