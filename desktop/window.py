"""Qt widgets over the existing evidence and review services."""
import json
import sqlite3
from html import escape

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter, QFrame,
    QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from copilot.agent import run_case
from copilot.data import ExcelProvider
from copilot.llm import ModelConfig, generate_draft, model_context
from copilot.store import TRANSITIONS, overdue
from desktop.config import save_settings
from desktop.theme import STYLE
from desktop.widgets import ChatFeed, EvidencePanel, MetricCard, SessionDelegate, TaskDelegate, navigation_button


def label(text, name=""):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def panel(name=""):
    widget = QWidget()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)
    return widget, layout


def records_html(title, rows):
    output = f"<h3>{escape(title)}</h3>"
    if not rows:
        return output + "<p>暂无记录</p>"
    for row in rows:
        names = {"message_id": "消息编号", "quote": "原文", "matched": "命中词"}
        output += "<p>" + "<br>".join(
            f"<b>{escape(names.get(k, str(k)))}</b>　{escape('、'.join(v) if isinstance(v, list) else str(v))}"
            for k, v in row.items()) + "</p><hr>"
    return output


def paragraph(value):
    return "<p>" + escape(str(value)).replace("\n", "<br>") + "</p>"


def detail_html(content):
    return "<html><body style='font-family:Microsoft YaHei UI;color:#34435b;font-size:13px;'>" + content + "</body></html>"


def risk_html(risk):
    return "<h3>" + escape(risk["level"]) + " · 风险依据</h3>" + paragraph(risk["reason"]) + records_html("引用原文", risk["evidence"])


class ModelWorker(QThread):
    result_ready = Signal(object)

    def __init__(self, result, config, parent=None):
        super().__init__(parent)
        self.result = result
        self.config = config

    def run(self):
        self.result_ready.emit(generate_draft(self.result, self.config))


class ReviewDialog(QDialog):
    def __init__(self, parent, result, original, edited, source):
        super().__init__(parent)
        self.setWindowTitle("确认并保存审核")
        self.resize(620, 610)
        self.result, self.original, self.edited, self.source = result, original, edited, source
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("核对这一次回应", "pageTitle"))
        layout.addWidget(label(result["case"]["session_id"] + "  ·  " + source, "pill"))
        layout.addWidget(label("保存至本地审核记录；不会发送给客户。", "muted"))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(edited)
        layout.addWidget(preview)
        form = QFormLayout()
        self.decision = QComboBox()
        self.decision.addItems(["采纳", "修改后确认", "驳回"])
        if edited != original:
            self.decision.setCurrentText("修改后确认")
        self.operator, self.owner, self.reason = QLineEdit(), QLineEdit(), QLineEdit()
        for title, field in [("审核操作", self.decision), ("操作人", self.operator),
                             ("处理负责人", self.owner), ("审核原因", self.reason)]:
            form.addRow(title, field)
        layout.addLayout(form)
        self.confirm = QCheckBox("我已核对内容，确认保存本次操作")
        layout.addWidget(self.confirm)
        for field in (self.operator, self.owner, self.reason):
            field.textChanged.connect(lambda: self.confirm.setChecked(False))
        self.decision.currentTextChanged.connect(lambda: self.confirm.setChecked(False))
        self.error = label("", "error")
        layout.addWidget(self.error)
        layout.addWidget(button("保存审核结果", self.save, True))

    def save(self):
        case = self.result["case"]
        try:
            review_id, created = self.parent().store.save(
                session=case["session_id"], cutoff=case["cutoff"], original=self.original,
                edited=self.edited, source=self.source, risk=self.result["risk"],
                decision=self.decision.currentText(), operator=self.operator.text(),
                owner=self.owner.text(), reason=self.reason.text(), confirmed=self.confirm.isChecked())
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        except sqlite3.Error:
            self.error.setText("记录暂时无法保存，请检查存储权限后重试。")
            return
        self.parent().statusBar().showMessage(f"审核 #{review_id} 已保存" if created else f"审核 #{review_id} 已存在，未重复写入")
        self.accept()


class ReplyDialog(QDialog):
    def __init__(self, parent, session, content):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("回复客户（本地模拟）")
        self.resize(600, 450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("回复客户", "pageTitle"))
        layout.addWidget(label(session + "  ·  已通过人工审核", "pill"))
        layout.addWidget(label("当前未接入真实客服渠道；确认后只会记录为本地模拟发送，并显示在本会话中。", "muted"))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(content)
        layout.addWidget(preview)
        form = QFormLayout()
        self.operator = QLineEdit()
        form.addRow("操作人", self.operator)
        layout.addLayout(form)
        self.confirm = QCheckBox("我已核对内容，确认执行本地模拟回复")
        layout.addWidget(self.confirm)
        self.operator.textChanged.connect(lambda: self.confirm.setChecked(False))
        self.error = label("", "error")
        layout.addWidget(self.error)
        layout.addWidget(button("确认回复客户", self.send, True))

    def send(self):
        try:
            message_id, created = self.parent().store.send_simulated(
                self.session, operator=self.operator.text(), confirmed=self.confirm.isChecked())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        except sqlite3.Error:
            self.error.setText("记录暂时无法保存，请检查存储权限后重试。")
            return
        self.parent().statusBar().showMessage(
            f"本地模拟回复 #{message_id} 已记录" if created else "该审核版本已模拟回复，未重复记录")
        self.accept()


class TaskDialog(QDialog):
    def __init__(self, parent, task):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"任务 {task['session']} · {task['status']}")
        self.resize(690, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("任务 " + task["session"], "pageTitle"))
        layout.addWidget(label(task["status"] + "  ·  负责人 " + task["owner"], "pill"))
        payload = json.loads(task["payload"])
        tabs = QTabWidget()
        detail = QTextBrowser()
        detail.setOpenLinks(False)
        detail.setHtml(detail_html("<h3>已确认的回复</h3>" + paragraph(payload["edited"]) + risk_html(payload["risk"])))
        tabs.addTab(detail, "确认内容与证据")
        events = QTextBrowser()
        events.setOpenLinks(False)
        timeline = ""
        for event in parent.store.events(task["session"]):
            state = json.loads(event["after_state"])
            timeline += "<h3>● " + escape(state["status"]) + "</h3>" + paragraph(event["reason"])
            timeline += paragraph(event["operator"] + "  ·  " + event["created"][:19].replace("T", " ")) + "<hr>"
        events.setHtml(detail_html(timeline or paragraph("暂无处理记录")))
        tabs.addTab(events, "处理时间线（UTC）")
        layout.addWidget(tabs)
        form = QFormLayout()
        self.owner, self.actor, self.reason = QLineEdit(task["owner"]), QLineEdit(), QLineEdit()
        self.status = QComboBox()
        self.status.addItems(TRANSITIONS[task["status"]])
        for title, field in [("负责人", self.owner), ("更新为", self.status),
                             ("本次操作人", self.actor), ("处理说明", self.reason)]:
            form.addRow(title, field)
        layout.addLayout(form)
        self.confirm = QCheckBox("确认本次分派和状态变更")
        layout.addWidget(self.confirm)
        for field in (self.owner, self.actor, self.reason):
            field.textChanged.connect(lambda: self.confirm.setChecked(False))
        self.status.currentTextChanged.connect(lambda: self.confirm.setChecked(False))
        self.error = label("", "error")
        layout.addWidget(self.error)
        layout.addWidget(button("保存任务变更", self.save, True))

    def save(self):
        try:
            changed = self.parent().store.update_task(self.task["session"],
                expected_updated=self.task["updated"], owner=self.owner.text(),
                status=self.status.currentText(), operator=self.actor.text(),
                reason=self.reason.text(), confirmed=self.confirm.isChecked())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        except sqlite3.Error:
            self.error.setText("记录暂时无法保存，请检查存储权限后重试。")
            return
        self.parent().statusBar().showMessage("任务已更新" if changed else "负责人和状态未变化")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, provider, store, settings=None, settings_directory=None, api_key=""):
        super().__init__()
        self.provider, self.store = provider, store
        self.settings = dict(settings or {})
        self.settings_directory = settings_directory
        self.api_key = api_key
        self.result = None
        self.worker = None
        self.drafts = {}
        self.setWindowTitle("共情副驾 · 桌面工作台")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 740)
        self.setStyleSheet(STYLE)
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        rail, rail_layout = panel("rail")
        rail.setFixedWidth(78)
        rail_layout.setContentsMargins(10, 22, 10, 16)
        rail_layout.setSpacing(18)
        brand = label("共", "railBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(44, 44)
        rail_layout.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
        self.inbox_nav = navigation_button("会话", "inbox", lambda: self.tabs.setCurrentIndex(0))
        self.board_nav = navigation_button("看板", "board", lambda: self.tabs.setCurrentIndex(1))
        for nav in (self.inbox_nav, self.board_nav):
            nav.setObjectName("nav")
            nav.setCheckable(True)
            rail_layout.addWidget(nav)
        self.inbox_nav.setChecked(True)
        rail_layout.addStretch()
        settings_nav = navigation_button("设置", "settings", self.configure_model)
        settings_nav.setObjectName("nav")
        rail_layout.addWidget(settings_nav)
        version = label("0.3.3", "muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rail_layout.addWidget(version)
        outer.addWidget(rail)
        workspace, layout = panel()
        layout.setContentsMargins(22, 17, 22, 12)
        layout.setSpacing(17)
        outer.addWidget(workspace, 1)
        top = QHBoxLayout()
        top_titles = QVBoxLayout()
        top_titles.setSpacing(3)
        top_titles.addWidget(label("共情副驾", "pageTitle"))
        tagline = label("让每一次回应，都有据可依。", "muted")
        tagline.setWordWrap(False)
        top_titles.addWidget(tagline)
        top.addLayout(top_titles)
        top.addStretch()
        self.workspace_badge = label("●  本地工作空间", "pill")
        top.addWidget(self.workspace_badge)
        self.open_button = button("选择 Excel", self.choose_file)
        top.addWidget(self.open_button)
        layout.addLayout(top)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        layout.addWidget(self.tabs)
        self.build_inbox()
        self.build_board()
        self.tabs.currentChanged.connect(self.navigate)
        self.statusBar().showMessage("   本地工作空间   /   审核后可执行本地模拟回复")
        self.populate_sessions()
        self.refresh_board()

    def navigate(self, index):
        self.inbox_nav.setChecked(index == 0)
        self.board_nav.setChecked(index == 1)
        if index == 1:
            self.refresh_board()

    def build_inbox(self):
        page, layout = panel()
        layout.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split)
        left, left_layout = panel("surface")
        left.setMinimumWidth(190)
        left.setMaximumWidth(210)
        left_layout.setContentsMargins(10, 18, 10, 8)
        heading = QHBoxLayout()
        heading.addWidget(label("收件箱", "heading"))
        heading.addStretch()
        self.session_count = label("0", "pill")
        heading.addWidget(self.session_count)
        left_layout.addLayout(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索会话或消息…")
        self.search.textChanged.connect(self.filter_sessions)
        left_layout.addWidget(self.search)
        self.sessions = QListWidget()
        self.sessions.setItemDelegate(SessionDelegate(self.sessions))
        self.sessions.setMouseTracking(True)
        self.sessions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sessions.currentItemChanged.connect(self.select_session)
        left_layout.addWidget(self.sessions)
        split.addWidget(left)
        center, center_layout = panel()
        center.setMinimumWidth(450)
        center_layout.setContentsMargins(4, 0, 4, 0)
        conversation_head, header_layout = panel("surface")
        header_layout.setContentsMargins(16, 13, 16, 13)
        header_row = QHBoxLayout()
        avatar = label("客", "avatar")
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(avatar)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label("选择一段会话", "heading")
        self.conversation_meta = label("从左侧收件箱开始", "muted")
        titles.addWidget(self.title)
        titles.addWidget(self.conversation_meta)
        header_row.addLayout(titles, 1)
        self.risk_badge = label("待核实", "pill")
        header_row.addWidget(self.risk_badge)
        header_layout.addLayout(header_row)
        center_layout.addWidget(conversation_head)
        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        self.chat = ChatFeed()
        self.chat.setMinimumHeight(180)
        vertical.addWidget(self.chat)
        composer, compose_layout = panel("surface")
        composer.setMinimumHeight(215)
        compose_layout.setContentsMargins(16, 12, 16, 12)
        compose_layout.setSpacing(5)
        row = QHBoxLayout()
        row.addWidget(label("回复草稿", "heading"))
        row.addStretch()
        self.model_button = button("✧  AI 建议", self.generate_model)
        self.model_button.setToolTip("使用已配置模型选择开场措辞")
        row.addWidget(self.model_button)
        self.reset_button = button("重置", self.reset_draft)
        self.reset_button.setObjectName("quiet")
        self.reset_button.setToolTip("恢复本地模板")
        row.addWidget(self.reset_button)
        compose_layout.addLayout(row)
        self.draft = QTextEdit()
        self.draft.setObjectName("draft")
        self.draft.setPlaceholderText("选择会话后，建议回复将显示在这里。")
        self.draft.setAcceptRichText(False)
        compose_layout.addWidget(self.draft)
        self.source_label = label("本地模板 · 内容待人工核对", "muted")
        compose_layout.addWidget(self.source_label)
        row = QHBoxLayout()
        history_button = button("◷  审核历史", self.show_history)
        history_button.setObjectName("quiet")
        row.addWidget(history_button)
        row.addStretch()
        self.review_button = button("审核并保存  →", self.review, True)
        row.addWidget(self.review_button)
        self.reply_button = button("回复客户  →", self.reply_customer, True)
        self.reply_button.setToolTip("记录本地模拟回复；当前未接入真实客服渠道")
        row.addWidget(self.reply_button)
        compose_layout.addLayout(row)
        vertical.addWidget(composer)
        vertical.setSizes([480, 255])
        center_layout.addWidget(vertical)
        split.addWidget(center)
        right, right_layout = panel("surface")
        right.setMinimumWidth(260)
        right_layout.setContentsMargins(16, 18, 8, 8)
        right_layout.addWidget(label("副驾洞察", "heading"))
        right_layout.addWidget(label("会话经过、风险与业务事实", "muted"))
        self.facts = EvidencePanel()
        right_layout.addWidget(self.facts)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([200, 690, 340])
        self.tabs.addTab(page, "会话收件箱")

    def build_board(self):
        page, layout = panel()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(label("任务概览", "pageTitle"))
        layout.addWidget(label("聚焦需要跟进的客户问题，保留每一步处理依据。", "muted"))
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.metric_cards = [MetricCard("已确认任务", "人工审核后创建", "#526dd4"),
                             MetricCard("待跟进", "待处理与处理中", "#567692"),
                             MetricCard("P0 待跟进", "优先核实与升级", "#c25670"),
                             MetricCard("超时提醒", "超过本地演示阈值", "#b78a40")]
        for card in self.metric_cards:
            cards.addWidget(card)
        layout.addLayout(cards)
        tasks_panel, tasks_layout = panel("surface")
        tasks_layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(tasks_panel, 1)
        row = QHBoxLayout()
        row.addWidget(label("任务列表", "heading"))
        row.addStretch()
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", *TRANSITIONS])
        self.status_filter.currentTextChanged.connect(self.refresh_board)
        row.addWidget(self.status_filter)
        row.addWidget(label("提醒阈值", "muted"))
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 720)
        self.threshold.setValue(24)
        self.threshold.setSuffix(" 小时")
        self.threshold.valueChanged.connect(self.refresh_board)
        row.addWidget(self.threshold)
        row.addWidget(button("刷新看板", self.refresh_board))
        tasks_layout.addLayout(row)
        self.task_list = QListWidget()
        self.task_list.setItemDelegate(TaskDelegate(self.task_list))
        self.task_list.itemDoubleClicked.connect(self.edit_task)
        tasks_layout.addWidget(self.task_list)
        self.empty_tasks = label("尚无匹配的任务\n\n在会话中审核并保存回复后，任务会出现在这里。", "muted")
        self.empty_tasks.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tasks_layout.addWidget(self.empty_tasks, 1)
        footer = QHBoxLayout()
        board_note = label("本地任务 · 姓名为手工记录 · 时间为 UTC", "muted")
        board_note.setWordWrap(False)
        footer.addWidget(board_note)
        footer.addStretch()
        self.task_action = button("查看与处理  →", self.edit_task, True)
        footer.addWidget(self.task_action)
        tasks_layout.addLayout(footer)
        self.tabs.addTab(page, "风险看板")

    def populate_sessions(self):
        self.result = None
        self.sessions.clear()
        self.search.clear()
        self.previews = {}
        self.model_button.setEnabled(self.provider is not None)
        self.review_button.setEnabled(self.provider is not None)
        self.reply_button.setEnabled(False)
        if self.provider is None:
            return
        ids = self.provider.sessions()
        ids = list(dict.fromkeys([s for s in ("S00268", "S00001") if s in ids] + ids))
        for session in ids:
            messages = self.provider.messages(session)
            latest = messages[-1]["message_text"].replace("\n", " ")
            self.previews[session] = session + " " + " ".join(m["message_text"] for m in messages)
            item = QListWidgetItem(f"客户 · {session}\n{latest[:25]}…")
            item.setData(Qt.ItemDataRole.UserRole, session)
            item.setData(Qt.ItemDataRole.UserRole + 1, {"preview": latest, "date": messages[-1]["发送时间"][:10]})
            self.sessions.addItem(item)
        self.session_count.setText(str(len(ids)))
        self.sessions.setCurrentRow(0)

    def filter_sessions(self, text):
        visible = 0
        for index in range(self.sessions.count()):
            item = self.sessions.item(index)
            item.setHidden(text.casefold() not in self.previews[item.data(Qt.ItemDataRole.UserRole)].casefold())
            visible += not item.isHidden()
        self.session_count.setText(str(visible))

    def remember_draft(self):
        if self.result:
            self.drafts[self.result["case"]["session_id"]] = (self.original, self.draft.toPlainText(), self.source)

    def select_session(self, item, previous=None):
        if item is None:
            return
        self.remember_draft()
        session = item.data(Qt.ItemDataRole.UserRole)
        messages = self.provider.messages(session)
        self.result = run_case(self.provider, session, messages[-1]["发送时间"])
        self.title.setText(f"客户 {session}")
        self.conversation_meta.setText(f"{len(messages)} 条历史消息  ·  完整会话")
        self.risk_badge.setText(self.result["risk"]["level"] + "  待核实")
        self.chat.set_messages(messages + self.simulated_chat_messages(session))
        self.original, edited, self.source = self.drafts.get(session, (self.result["draft"], self.result["draft"], "本地模板"))
        self.draft.setPlainText(edited)
        self.source_label.setText(self.source + " · 审核保存后可回复客户（本地模拟）")
        self.reply_button.setEnabled(self.store.task(session) is not None)
        self.facts.show_result(self.result, self.provider)

    def reset_draft(self):
        if self.result:
            self.original = self.result["draft"]
            self.source = "本地模板"
            self.draft.setPlainText(self.original)
            self.source_label.setText("本地模板 · 审核保存后可回复客户（本地模拟）")

    def review(self):
        if self.result:
            ReviewDialog(self, self.result, self.original, self.draft.toPlainText(), self.source).exec()
            self.refresh_board()
            self.reply_button.setEnabled(self.store.task(self.result["case"]["session_id"]) is not None)

    def simulated_chat_messages(self, session):
        return [dict(角色="客服", 发送时间=row["created"].replace("T", " ")[:19],
                     内容类型="文字", image_path="", message_id=f"LOCAL-{row['id']}",
                     message_text=row["content"] + "\n（本地模拟回复，未送达外部渠道）")
                for row in self.store.simulated_messages(session)]

    def reply_customer(self):
        if not self.result:
            return
        session = self.result["case"]["session_id"]
        task = self.store.task(session)
        if not task:
            QMessageBox.information(self, "请先审核", "请先点击“审核并保存”，再回复客户。")
            return
        content = self.store.reviewed_reply(session) or ""
        dialog = ReplyDialog(self, session, content)
        dialog.exec()
        self.chat.set_messages(self.provider.messages(session) + self.simulated_chat_messages(session))

    def show_history(self):
        if not self.result:
            return
        history = self.store.history(self.result["case"]["session_id"])
        dialog = QDialog(self)
        dialog.setWindowTitle("审核历史（UTC）")
        dialog.resize(720, 650)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.addWidget(label("每一次确认，都有记录", "pageTitle"))
        text = QTextBrowser()
        text.setOpenLinks(False)
        content = ""
        for entry in history:
            content += f"<h2>#{entry['id']} · {escape(entry['decision'])}</h2>"
            content += paragraph(entry["operator"] + "  ·  " + entry["created"][:19].replace("T", " "))
            content += paragraph("负责人：" + (entry["owner"] or "未指定") + "  /  来源：" + entry["source"])
            content += "<h3>审核原因</h3>" + paragraph(entry["reason"])
            content += "<h3>审核内容</h3>" + paragraph(entry["edited"])
            content += "<h3>原始建议</h3>" + paragraph(entry["original"])
            content += risk_html(entry["risk"]) + "<hr>"
        text.setHtml(detail_html(content or paragraph("当前会话还没有审核记录。")))
        layout.addWidget(text)
        dialog.exec()

    def refresh_board(self, *_):
        tasks = self.store.tasks()
        pending = [t for t in tasks if t["status"] in {"待处理", "处理中"}]
        counts = [len(tasks), len(pending), sum(json.loads(t['payload'])['risk']['level'] == 'P0' for t in pending),
                  sum(overdue(t, self.threshold.value()) for t in tasks)]
        for card, count in zip(self.metric_cards, counts):
            card.number.setText(str(count))
        self.task_list.clear()
        for task in tasks:
            if self.status_filter.currentText() not in ("全部", task["status"]):
                continue
            risk = json.loads(task["payload"])["risk"]["level"]
            item = QListWidgetItem(f"{task['session']}   ·   {risk}   ·   {task['status']}   ·   负责人：{task['owner']}\n"
                f"创建：{task['created']}   最近更新：{task['updated']}"
                + ("   已超时" if overdue(task, self.threshold.value()) else ""))
            item.setData(Qt.ItemDataRole.UserRole, task)
            item.setData(Qt.ItemDataRole.UserRole + 1, overdue(task, self.threshold.value()))
            self.task_list.addItem(item)
        if self.task_list.count():
            self.task_list.setCurrentRow(0)
        has_tasks = self.task_list.count() > 0
        self.task_list.setVisible(has_tasks)
        self.empty_tasks.setVisible(not has_tasks)
        self.task_action.setEnabled(has_tasks)

    def edit_task(self, *_):
        item = self.task_list.currentItem()
        if item:
            TaskDialog(self, item.data(Qt.ItemDataRole.UserRole)).exec()
            self.refresh_board()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择业务数据", "", "Excel 工作簿 (*.xlsx)")
        if not path:
            return
        try:
            provider = ExcelProvider(path)
            if not provider.sessions():
                raise ValueError("工作簿没有聊天会话。")
            settings = dict(self.settings, data_path=path)
            save_settings(settings, self.settings_directory)
        except Exception:
            QMessageBox.warning(self, "无法打开", "请检查文件是否可读、包含聊天记录和订单等必要工作表，以及时间字段格式。")
            return
        self.settings = settings
        self.provider = provider
        self.drafts.clear()
        self.populate_sessions()
        self.statusBar().showMessage("已载入业务数据：" + path)

    def configure_model(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("模型连接设置")
        dialog.resize(560, 310)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        layout.addWidget(label("连接你的 AI 副驾", "pageTitle"))
        layout.addWidget(label("模型仅选择开场措辞。API Key 只在本次运行保留。", "muted"))
        form = QFormLayout()
        base = QLineEdit(self.settings.get("base_url", ""))
        base.setPlaceholderText("https://…/v1")
        model = QLineEdit(self.settings.get("model", ""))
        key = QLineEdit(self.api_key)
        key.setEchoMode(QLineEdit.EchoMode.Password)
        for name, field in [("接口地址", base), ("模型名称", model), ("API Key", key)]:
            form.addRow(name, field)
        layout.addLayout(form)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dict(self.settings, base_url=base.text().strip(), model=model.text().strip())
            save_settings(settings, self.settings_directory)
            self.settings, self.api_key = settings, key.text()

    def generate_model(self):
        if not self.result or (self.worker and self.worker.isRunning()):
            return
        config = ModelConfig(self.settings.get("base_url", ""), self.settings.get("model", ""), self.api_key)
        try:
            config.validate()
        except ValueError as exc:
            QMessageBox.information(self, "请配置模型", str(exc))
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("生成模型建议")
        dialog.setText("将向配置的模型接口发送当前会话的脱敏买家文字，用于选择开场措辞。")
        dialog.setDetailedText(json.dumps(model_context(self.result), ensure_ascii=False, indent=2))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if dialog.exec() != QMessageBox.StandardButton.Ok:
            return
        self.model_context_session = self.result["case"]["session_id"]
        self.model_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.sessions.setEnabled(False)
        self.draft.setReadOnly(True)
        self.reset_button.setEnabled(False)
        self.review_button.setEnabled(False)
        self.statusBar().showMessage("正在生成模型建议…")
        self.worker = ModelWorker(self.result, config, self)
        self.worker.result_ready.connect(self.model_completed)
        self.worker.finished.connect(self.model_finished)
        self.worker.start()

    def model_completed(self, output):
        self.original = output["text"]
        self.source = "模型辅助草稿" if output["status"] == "model" else "回退模板"
        self.draft.setPlainText(self.original)
        self.source_label.setText(self.source + " · " + output["notice"])
        self.statusBar().showMessage(output["notice"])

    def model_finished(self):
        self.model_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.sessions.setEnabled(True)
        self.draft.setReadOnly(False)
        self.reset_button.setEnabled(True)
        self.review_button.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage("模型请求仍在进行，请等待返回后关闭。")
            event.ignore()
            return
        event.accept()
