"""Qt widgets over the existing evidence and review services."""
import json
import sqlite3
import getpass
from uuid import uuid4
from html import escape

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QPoint
from PySide6.QtGui import QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter, QFrame,
    QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget, QToolButton,
)

from copilot.agent import run_case, assess
from copilot.data import ExcelProvider
from copilot.llm import ModelConfig
from copilot.reply_llm import generate_reply
from copilot.summary import digest
from copilot.store import TRANSITIONS, overdue
from copilot.reports import ReportStore
from desktop.reporting import ReportDialog, HandleReportDialog, AllChatsDialog
from desktop.config import save_settings
from desktop.theme import STYLE, scaled_style
from desktop.controls import SoftComboBox as QComboBox
from desktop.controls import SoftMenu as QMenu
from desktop.inbox_controls import InboxMenu
from desktop.navigation import InboxSplitter, MessageMap, SlidingPanel, SessionItem
from desktop.icons import svg_icon
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

    def __init__(self, result, config, parent=None, draft='', local_messages=(), summary=None):
        super().__init__(parent)
        self.result = result
        self.config = config
        self.draft, self.local_messages = draft, local_messages
        self.summary = summary

    def run(self):
        self.result_ready.emit(generate_reply(self.result, self.config, self.draft, self.local_messages, self.summary))


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
        self.reports = ReportStore(store)
        self.settings = dict(settings or {})
        self.settings_directory = settings_directory
        self.api_key = api_key
        self.result = None
        self.worker = None
        self.summary_worker = None
        self.drafts = {}
        self.stale_drafts = set()
        self.loading_draft = False
        self.draft_revision = 0
        self.send_token = str(uuid4())
        self.setWindowTitle("共情副驾 · 桌面工作台")
        self.brand_icon = svg_icon("messages-square", "#ffffff", brand=True)
        self.setWindowIcon(self.brand_icon)
        self.resize(1440, 900)
        self.setMinimumSize(1120, 740)
        self.setStyleSheet(STYLE)
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        rail, rail_layout = panel("rail")
        self.rail = rail
        rail.setFixedWidth(48)
        rail_layout.setContentsMargins(4, 14, 4, 12)
        rail_layout.setSpacing(12)
        brand = label("", "brandMark")
        self.brand_mark = brand
        brand.setPixmap(self.brand_icon.pixmap(256, 256))
        brand.setScaledContents(True)
        brand.setAccessibleName("共情副驾")
        brand.setToolTip("共情副驾 · 0.6.4")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(36, 36)
        rail_layout.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
        self.inbox_nav = navigation_button("会话", "inbox", lambda: self.tabs.setCurrentIndex(0))
        self.board_nav = navigation_button("主任", "board", lambda: self.tabs.setCurrentIndex(1))
        for nav in (self.inbox_nav, self.board_nav):
            nav.setObjectName("nav")
            nav.setCheckable(True)
            rail_layout.addWidget(nav)
        self.inbox_nav.setChecked(True)
        rail_layout.addStretch()
        self.workspace_badge = label("●", "railStatus")
        self.workspace_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workspace_badge.setToolTip("本地工作空间 · 数据与模拟操作保存在本机")
        self.workspace_badge.setAccessibleName("本地工作空间")
        rail_layout.addWidget(self.workspace_badge)
        self.open_button = QToolButton()
        self.open_button.setObjectName("nav")
        self.open_button.setIcon(svg_icon("file-search"))
        self.open_button.setIconSize(QSize(20, 20))
        self.open_button.setFixedSize(40, 40)
        self.open_button.setToolTip("选择 Excel 工作簿")
        self.open_button.setAccessibleName("选择 Excel 工作簿")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self.choose_file)
        self.open_button.hide()
        settings_nav = navigation_button("设置", "settings", self.show_settings_menu)
        self.settings_nav = settings_nav
        settings_nav.setObjectName("nav")
        rail_layout.addWidget(settings_nav)
        self.settings_menu = QMenu(self)
        self.simulation_action = self.settings_menu.addAction("模拟对话测试", self.open_simulation)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction("模型连接设置", self.configure_model)
        self.settings_menu.addAction("打开数据文件", self.choose_file)
        outer.addWidget(rail)
        workspace, layout = panel()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        outer.addWidget(workspace, 1)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        layout.addWidget(self.tabs)
        self.build_inbox()
        self.build_board()
        self.zoom_percent = 100
        for key in ("Ctrl++", "Ctrl+="):
            QShortcut(QKeySequence(key), self, activated=lambda: self.adjust_zoom(1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.adjust_zoom(-1))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.set_zoom(100))
        self.tabs.currentChanged.connect(self.navigate)
        self.statusBar().showMessage("   本地工作空间   /   编辑回复后点击模拟发送")
        self.populate_sessions()
        self.source_timer = QTimer(self)
        self.source_timer.timeout.connect(self.poll_source)
        self.source_timer.start(3000)
        self.report_timer = QTimer(self)
        self.report_timer.timeout.connect(self.refresh_board)
        self.report_timer.start(3000)
        self.refresh_board()

    def show_settings_menu(self):
        anchor = self.settings_nav
        self.settings_menu.popup(anchor.mapToGlobal(anchor.rect().topRight()) -
                                 QPoint(0, self.settings_menu.sizeHint().height()))

    def open_simulation(self):
        from desktop.simulation import SimulationWindow
        from desktop.config import user_directory
        window = getattr(self, 'simulation_window', None)
        if window is None or not window.isVisible():
            directory = (self.settings_directory or user_directory()) / 'simulation'
            window = SimulationWindow(directory, self.settings, self.api_key)
            self.simulation_window = window
        window.show()
        window.raise_()
        window.activateWindow()

    def navigate(self, index):
        self.inbox_nav.setChecked(index == 0)
        self.board_nav.setChecked(index == 1)
        if index == 1:
            self.refresh_board()

    def adjust_zoom(self, direction):
        levels = (80, 90, 100, 110, 120, 130)
        index = levels.index(self.zoom_percent)
        self.set_zoom(levels[max(0, min(len(levels) - 1, index + direction))])

    def set_zoom(self, percent):
        if percent == self.zoom_percent:
            return
        self.chat.preserve_reading_position()
        self.zoom_percent = percent
        factor = percent / 100
        size = lambda value: round(value * factor)
        self.setStyleSheet(scaled_style(percent))
        self.rail.setFixedWidth(size(48))
        self.brand_mark.setFixedSize(size(36), size(36))
        for nav in (self.inbox_nav, self.board_nav, self.settings_nav, self.open_button):
            nav.setFixedSize(size(40), size(40))
            nav.setIconSize(QSize(size(20), size(20)))
        for action, icon in ((self.filter_button, 20), (self.sort_button, 20),
                             (self.clear_filters_button, 14)):
            action.setFixedSize(size(36), size(36))
            action.setIconSize(QSize(size(icon), size(icon)))
        for action, width in ((self.risk_evidence, 28), (self.summary_toggle, 30)):
            action.setFixedSize(size(width), size(width))
        self.header_avatar.setFixedSize(size(38), size(38))
        self.composer.setMinimumHeight(size(215))
        self.message_map.set_zoom(factor)
        self.sessions.itemDelegate().set_zoom(factor)
        self.sessions.doItemsLayout()
        self.task_list.itemDelegate().set_zoom(factor)
        self.task_list.doItemsLayout()
        self.chat.set_zoom(factor)
        self.statusBar().showMessage(f"界面缩放 {percent}% · Ctrl+0 恢复默认", 3000)

    def build_inbox(self):
        page, layout = panel()
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary_width = 350
        split = InboxSplitter()
        self.inbox_split = split
        split.setChildrenCollapsible(False)
        layout.addWidget(split)
        left, left_layout = panel("surface")
        self.inbox_panel = left
        left.setMinimumWidth(210)
        left.setMaximumWidth(360)
        left_layout.setContentsMargins(10, 18, 10, 8)
        heading = QHBoxLayout()
        heading.addWidget(label("收件箱", "heading"))
        heading.addStretch()
        self.session_count = label("0", "pill")
        heading.addWidget(self.session_count)
        left_layout.addLayout(heading)
        self.search = QLineEdit()
        self.search.setObjectName("inboxSearch")
        self.search.setPlaceholderText("搜索会话或消息")
        self.search.addAction(svg_icon("search", "#777777"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMinimumWidth(0)
        self.search.textChanged.connect(self.filter_sessions)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(self.search, 1)
        self.filter_button = QToolButton()
        self.filter_button.setObjectName("inboxAction")
        self.filter_button.setFixedSize(36, 36)
        self.filter_button.setIconSize(QSize(20, 20))
        self.filter_button.setIcon(svg_icon("funnel", "#777777"))
        self.filter_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.filter_button.setAccessibleName("会话筛选")
        self.filter_button.setToolTip("按风险、主任上报状态和图片消息筛选")
        self.sort_mode = 'latest'
        self.sort_button = QToolButton()
        self.sort_button.setObjectName("inboxAction")
        self.sort_button.setFixedSize(36, 36)
        self.sort_button.setIconSize(QSize(20, 20))
        self.sort_button.setIcon(svg_icon("sort-arrows", "#777777"))
        self.sort_button.setAccessibleName("会话排序")
        self.sort_button.setToolTip("排序：最近消息 · 降序（最新在前）")
        self.sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = InboxMenu(self.sort_button)
        group = QActionGroup(menu)
        self.sort_actions = {}
        for title, mode in [('最近消息  ↓', 'recent'),
                            ('风险优先（P0 → P1 → 待核实）', 'risk'), ('会话编号', 'session')]:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(mode == 'recent')
            self.sort_actions[mode] = action
            group.addAction(action)
            action.triggered.connect(lambda checked=False, m=mode, t=title: self.choose_session_sort(m, t))
        self.sort_button.setMenu(menu)
        filter_row.addWidget(self.sort_button)
        filter_row.addWidget(self.filter_button)
        self.clear_filters_button = QToolButton()
        self.clear_filters_button.setObjectName("inboxAction")
        self.clear_filters_button.setFixedSize(28, 28)
        self.clear_filters_button.setIconSize(QSize(14, 14))
        self.clear_filters_button.setIcon(svg_icon("x"))
        self.clear_filters_button.setToolTip("清除筛选与搜索")
        self.clear_filters_button.setAccessibleName("清除筛选与搜索")
        self.clear_filters_button.clicked.connect(self.clear_session_filters)
        self.clear_filters_button.setParent(left)
        left_layout.addLayout(filter_row)
        self.filter_panel = QWidget()
        filters = QVBoxLayout(self.filter_panel)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(6)
        self.risk_filter = QComboBox()
        for title, value in [("全部风险等级", ""), ("P0 · 优先核实", "P0"),
                             ("P1 · 服务风险", "P1"), ("待核实 · 规则未命中", "待核实")]:
            self.risk_filter.addItem(title, value)
        self.report_filter = QComboBox()
        for title, value in [("全部上报状态", ""), ("有待处理上报", "pending"),
                             ("已上报主任", "reported"), ("未上报主任", "unreported")]:
            self.report_filter.addItem(title, value)
        self.image_filter = QComboBox()
        for title, value in [("全部消息类型", ""), ("含图片消息", "image"), ("仅文字消息", "text")]:
            self.image_filter.addItem(title, value)
        for title, combo in [("风险等级", self.risk_filter), ("主任上报状态", self.report_filter),
                             ("消息类型", self.image_filter)]:
            combo.setAccessibleName(title)
            filters.addWidget(combo)
            combo.currentIndexChanged.connect(self.filter_sessions)
        self.filter_panel.hide()
        self.filter_panel.setParent(left)
        self.filter_menu = InboxMenu(self.filter_button)
        self.filter_actions = []
        for title, combo in [("风险等级", self.risk_filter), ("主任上报状态", self.report_filter),
                             ("消息类型", self.image_filter)]:
            self.filter_menu.addSection(title)
            group = QActionGroup(self.filter_menu)
            actions = []
            for index in range(combo.count()):
                action = self.filter_menu.addAction(combo.itemText(index))
                action.setCheckable(True)
                action.setChecked(index == combo.currentIndex())
                group.addAction(action)
                action.triggered.connect(lambda checked=False, c=combo, i=index: c.setCurrentIndex(i))
                actions.append(action)
            self.filter_actions.append((combo, actions))
        self.filter_menu.addSeparator()
        self.filter_menu.addAction("清除筛选与搜索", self.clear_session_filters)
        self.filter_button.setMenu(self.filter_menu)
        self.filter_notice = label("", "muted")
        self.filter_notice.hide()
        left_layout.addWidget(self.filter_notice)
        self.sessions = QListWidget()
        self.sessions.setItemDelegate(SessionDelegate(self.sessions))
        self.sessions.setMouseTracking(True)
        self.sessions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sessions.currentItemChanged.connect(self.select_session)
        left_layout.addWidget(self.sessions)
        split.addWidget(left)
        center, center_layout = panel()
        center.setMinimumWidth(420)
        center_layout.setContentsMargins(4, 0, 4, 0)
        conversation_head, header_layout = panel("surface")
        header_layout.setContentsMargins(16, 13, 16, 13)
        header_row = QHBoxLayout()
        avatar = label("客", "avatar")
        self.header_avatar = avatar
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
        self.risk_badge = label("待核实", "riskBadge")
        header_row.addWidget(self.risk_badge)
        self.risk_evidence = QToolButton()
        self.risk_evidence.setObjectName("evidenceButton")
        self.risk_evidence.setIcon(svg_icon("file-search"))
        self.risk_evidence.setFixedSize(28, 28)
        self.risk_evidence.setToolTip("查看风险依据")
        self.risk_evidence.setAccessibleName("查看风险依据")
        self.risk_evidence.clicked.connect(self.show_risk_evidence)
        header_row.addWidget(self.risk_evidence)
        self.summary_toggle = QToolButton()
        self.summary_toggle.setObjectName("panelToggle")
        self.summary_toggle.setIcon(svg_icon("panel-right"))
        self.summary_toggle.setFixedSize(30, 30)
        self.summary_toggle.setCheckable(True)
        self.summary_toggle.setChecked(True)
        self.summary_toggle.setAccessibleName("展开或收起服务摘要")
        self.summary_toggle.setToolTip("收起服务摘要")
        header_row.addWidget(self.summary_toggle)
        header_layout.addLayout(header_row)
        center_layout.addWidget(conversation_head)
        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        self.chat = ChatFeed()
        self.chat.setMinimumHeight(180)
        chat_area = QWidget()
        chat_layout = QHBoxLayout(chat_area)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(2)
        self.message_map = MessageMap(self.chat)
        chat_layout.addWidget(self.message_map)
        chat_layout.addWidget(self.chat, 1)
        vertical.addWidget(chat_area)
        composer, compose_layout = panel("surface")
        self.composer = composer
        composer.setMinimumHeight(215)
        compose_layout.setContentsMargins(16, 12, 16, 12)
        compose_layout.setSpacing(5)
        row = QHBoxLayout()
        row.addWidget(label("回复草稿", "heading"))
        row.addStretch()
        self.model_button = button("✧  AI 建议", self.generate_model)
        self.model_button.setToolTip("将会话和已有草稿发送到已配置的模型接口，生成回复建议")
        row.addWidget(self.model_button)
        self.reset_button = button("清空", self.reset_draft)
        self.reset_button.setObjectName("quiet")
        self.reset_button.setToolTip("清空当前未发送的草稿")
        row.addWidget(self.reset_button)
        compose_layout.addLayout(row)
        self.draft = QTextEdit()
        self.draft.setObjectName("draft")
        self.draft.setPlaceholderText("输入回复，或点击“AI 建议”生成后修改……")
        self.draft.setAcceptRichText(False)
        compose_layout.addWidget(self.draft)
        self.source_label = label("未接入真实客服渠道 · 仅本地模拟发送", "muted")
        compose_layout.addWidget(self.source_label)
        row = QHBoxLayout()
        history_button = button("◷  操作记录", self.show_history)
        history_button.setObjectName("quiet")
        row.addWidget(history_button)
        self.report_button = button("上报主任", self.report_messages)
        row.addWidget(self.report_button)
        row.addStretch()
        self.reply_button = button("模拟发送  →", self.reply_customer, True)
        self.reply_button.setToolTip("记录本地模拟回复；当前未接入真实客服渠道")
        row.addWidget(self.reply_button)
        self.draft.textChanged.connect(self.draft_changed)
        compose_layout.addLayout(row)
        vertical.addWidget(composer)
        vertical.setSizes([480, 255])
        center_layout.addWidget(vertical)
        split.addWidget(center)
        right, right_layout = panel("surface")
        right.setMinimumWidth(330)
        right_layout.setContentsMargins(16, 18, 8, 8)
        right_layout.addWidget(label("服务摘要", "heading"))
        self.facts = EvidencePanel()
        self.facts.state_path = self.store.path
        right_layout.addWidget(self.facts)
        self.summary_panel = SlidingPanel(right)
        split.addWidget(self.summary_panel)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([240, 710, 350])
        split.setCollapsible(0, True)
        split.handle(1).setToolTip("左右拖动调整会话列表；拖到最左侧收起，向右拉开。双击也可切换。")
        self.summary_toggle.toggled.connect(self.toggle_summary_panel)
        self.tabs.addTab(page, "会话收件箱")

    def toggle_summary_panel(self, visible):
        self.chat.preserve_reading_position()
        self.summary_panel.slide(visible)
        self.summary_toggle.setToolTip("收起服务摘要" if visible else "展开服务摘要")

    def show_risk_evidence(self):
        if not self.result:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("风险依据 · " + self.result['case']['session_id'])
        dialog.resize(600, 480)
        layout = QVBoxLayout(dialog)
        detail = QTextBrowser()
        detail.setOpenLinks(False)
        detail.setHtml(detail_html(risk_html(self.result['risk'])))
        layout.addWidget(detail)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def build_board(self):
        page, layout = panel()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(label("主任工作台", "pageTitle"))
        layout.addWidget(label("只有客服主动上报才进入提醒；全部聊天可随时查阅。", "muted"))
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.metric_cards = [MetricCard("客服上报", "客服主动选择消息并提交", "#526dd4"),
                             MetricCard("待处理上报", "待处理与处理中", "#567692"),
                             MetricCard("P0 已上报", "优先核实与升级", "#c25670"),
                             MetricCard("超时提醒", "超过本地演示阈值", "#b78a40")]
        for card in self.metric_cards:
            cards.addWidget(card)
        layout.addLayout(cards)
        tasks_panel, tasks_layout = panel("surface")
        tasks_layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(tasks_panel, 1)
        row = QHBoxLayout()
        row.addWidget(label("上报列表", "heading"))
        row.addStretch()
        self.status_filter = QComboBox()
        self.status_filter.addItems(["待处理", "处理中", "已处理", "全部"])
        self.status_filter.currentTextChanged.connect(self.refresh_board)
        row.addWidget(self.status_filter)
        row.addWidget(label("提醒阈值", "muted"))
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 720)
        self.threshold.setValue(24)
        self.threshold.setSuffix(" 小时")
        self.threshold.valueChanged.connect(self.refresh_board)
        row.addWidget(self.threshold)
        row.addWidget(button("查看全部聊天", self.browse_all_chats))
        row.addWidget(button("刷新", self.refresh_board))
        tasks_layout.addLayout(row)
        self.task_list = QListWidget()
        self.task_list.setItemDelegate(TaskDelegate(self.task_list))
        self.task_list.itemDoubleClicked.connect(self.edit_task)
        tasks_layout.addWidget(self.task_list)
        self.empty_tasks = label("暂无这类上报\n\n客服选择消息并点击“上报主任”后，才会出现在这里。", "muted")
        self.empty_tasks.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tasks_layout.addWidget(self.empty_tasks, 1)
        footer = QHBoxLayout()
        board_note = label("本地上报 · 角色为演示入口，尚未接入登录权限 · 时间为 UTC", "muted")
        board_note.setWordWrap(False)
        footer.addWidget(board_note)
        footer.addStretch()
        self.task_action = button("查看与处理  →", self.edit_task, True)
        footer.addWidget(self.task_action)
        tasks_layout.addLayout(footer)
        self.tabs.addTab(page, "主任工作台")

    def populate_sessions(self):
        self.result = None
        self.sessions.clear()
        self.search.clear()
        self.previews = {}
        self.session_filter_data = {}
        self.model_button.setEnabled(self.provider is not None)
        self.report_button.setEnabled(self.provider is not None)
        self.reply_button.setEnabled(False)
        if self.provider is None:
            self.filter_sessions()
            return
        ids = self.provider.sessions()
        ids = list(dict.fromkeys([s for s in ("S00268", "S00001") if s in ids] + ids))
        for session in ids:
            messages = self.provider.messages(session)
            latest = messages[-1]["message_text"].replace("\n", " ")
            self.previews[session] = session + " " + " ".join(m["message_text"] for m in messages)
            self.session_filter_data[session] = self.session_filter_metadata(messages)
            local = self.simulated_chat_messages(session)
            if local:
                self.session_filter_data[session]['latest'] = max(messages[-1]['发送时间'], local[-1]['发送时间'])
            item = SessionItem(f"客户 · {session}\n{latest[:25]}…")
            item.setData(Qt.ItemDataRole.UserRole, session)
            item.setData(Qt.ItemDataRole.UserRole + 1, {"preview": latest, "date": messages[-1]["发送时间"][:10]})
            self.sessions.addItem(item)
        self.session_count.setText(str(len(ids)))
        self.sessions.setCurrentRow(0)
        self.sort_sessions()
        self.filter_sessions()

    @staticmethod
    def session_filter_metadata(messages):
        return {"risk": assess({"messages": messages})["level"],
                "latest": messages[-1]['发送时间'],
                "image": any(m.get("image_path") or m.get("内容类型") == "图片" for m in messages)}

    def choose_session_sort(self, mode, title):
        if mode == 'recent':
            mode = 'oldest' if self.sort_mode == 'latest' else 'latest'
        self.set_session_sort(mode, title)

    def set_session_sort(self, mode, title):
        self.sort_mode = mode
        recent = mode in ('latest', 'oldest')
        arrow = '↑' if mode == 'oldest' else '↓'
        self.sort_actions['recent'].setText('最近消息  ' + arrow if recent else '最近消息')
        for key, action in self.sort_actions.items():
            action.setChecked(key == ('recent' if recent else mode))
        if recent:
            title = '最近消息 · ' + ('升序（最早在前）' if mode == 'oldest' else '降序（最新在前）')
        self.sort_button.setIcon(svg_icon('sort-arrows', '#777777'))
        self.sort_button.setToolTip("排序：" + title)
        self.sort_button.setAccessibleName("排序：" + title)
        self.sort_sessions()

    def sort_sessions(self):
        for index in range(self.sessions.count()):
            item = self.sessions.item(index)
            session = item.data(Qt.ItemDataRole.UserRole)
            meta = self.session_filter_data[session]
            if self.sort_mode == 'risk':
                key = ({'P0': 0, 'P1': 1}.get(meta['risk'], 2), session)
            elif self.sort_mode == 'session':
                key = (session,)
            else:
                key = (meta['latest'], session)
            item.setData(Qt.ItemDataRole.UserRole + 2, key)
        self.sessions.sortItems(Qt.SortOrder.DescendingOrder if self.sort_mode == 'latest' else Qt.SortOrder.AscendingOrder)

    def clear_session_filters(self):
        for combo in (self.risk_filter, self.report_filter, self.image_filter):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.search.clear()
        self.filter_sessions()

    def filter_sessions(self, *_):
        text = self.search.text().strip().casefold()
        risk, report, image = (c.currentData() for c in
                               (self.risk_filter, self.report_filter, self.image_filter))
        statuses = getattr(self, "session_report_statuses", {})
        visible = 0
        for index in range(self.sessions.count()):
            item = self.sessions.item(index)
            session = item.data(Qt.ItemDataRole.UserRole)
            meta = self.session_filter_data[session]
            reports = statuses.get(session, set())
            matches = (text in self.previews[session].casefold()
                       and (not risk or meta["risk"] == risk)
                       and (not image or bool(meta["image"]) == (image == "image"))
                       and (not report or (report == "reported" and bool(reports))
                            or (report == "unreported" and not reports)
                            or (report == "pending" and bool(reports & {"待处理", "处理中"}))))
            item.setHidden(not matches)
            visible += not item.isHidden()
        self.session_count.setText(str(visible))
        active = sum(bool(v) for v in (risk, report, image))
        self.filter_button.setToolTip(f"筛选：已启用 {active} 项" if active else "按风险、上报状态和图片消息筛选")
        self.filter_button.setProperty('active', bool(active))
        self.filter_button.style().unpolish(self.filter_button)
        self.filter_button.style().polish(self.filter_button)
        self.clear_filters_button.hide()
        self.search.setClearButtonEnabled(bool(text))
        for combo, actions in self.filter_actions:
            for index, action in enumerate(actions):
                action.setChecked(index == combo.currentIndex())
        current = self.sessions.currentItem()
        notice = "没有符合条件的会话" if not visible else ""
        if current and current.isHidden():
            notice += ("\n" if notice else "") + "右侧保留当前会话，选择列表项后切换。"
        self.filter_notice.setText(notice)
        self.filter_notice.setVisible(bool(notice))

    def remember_draft(self):
        if self.result:
            self.store.save_composer_draft(self.draft_scope(), self.result['case']['session_id'],
                dict(original=self.original, edited=self.draft.toPlainText(), source=self.source,
                     token=self.send_token, fingerprint=self.draft_fingerprint))

    def draft_scope(self):
        return str(self.provider.source.resolve()).casefold()

    def update_send_button(self):
        self.reply_button.setEnabled(bool(self.result and self.draft.toPlainText().strip()
            and self.result['case']['session_id'] not in self.stale_drafts))

    def draft_changed(self):
        if self.loading_draft or not self.result:
            return
        self.draft_revision += 1
        self.send_token = str(uuid4())
        self.update_send_button()
        try:
            self.remember_draft()
        except (sqlite3.Error, OSError):
            self.source_label.setText('草稿保存失败，文字仍在输入框；请勿关闭软件。')

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
        self.risk_badge.setProperty("level", self.result["risk"]["level"])
        self.risk_badge.style().unpolish(self.risk_badge)
        self.risk_badge.style().polish(self.risk_badge)
        self.chat.set_messages(messages + self.simulated_chat_messages(session))
        saved = self.store.composer_draft(self.draft_scope(), session) or {}
        self.draft_fingerprint = saved.get('fingerprint', json.dumps(self.result['case'], sort_keys=True))
        self.original, edited, self.source = saved.get('original', ''), saved.get('edited', ''), saved.get('source', '人工输入')
        self.send_token = saved.get('token', str(uuid4()))
        self.loading_draft = True
        self.draft.setPlainText(edited)
        self.loading_draft = False
        self.draft_revision += 1
        self.source_label.setText("草稿自动保存 · 仅本地模拟发送，未接入客户渠道")
        if saved.get('fingerprint') and saved['fingerprint'] != json.dumps(self.result['case'], sort_keys=True):
            self.stale_drafts.add(session)
        self.update_send_button()
        self.facts.show_result(self.result, self.provider)
        if session in self.stale_drafts:
            self.reply_button.setEnabled(False)
            self.source_label.setText('资料已变化，请清空后重新输入，或重新生成建议后核对。')
        if not hasattr(self, '_source_stamp'):
            stat = self.provider.source.stat()
            self._source_stamp = (stat.st_mtime_ns, stat.st_size)
        self.filter_sessions()

    def poll_source(self):
        """Reload changed local input, but never replace a handover without a click."""
        if not self.provider or not self.result:
            return
        try:
            stat = self.provider.source.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp == getattr(self, '_source_stamp', None):
                return
            if not hasattr(self, '_source_stamp'):
                self._source_stamp = stamp
                return
            provider = ExcelProvider(self.provider.source)
            session = self.result['case']['session_id']
            messages = provider.messages(session)
            if not messages:
                self.statusBar().showMessage('新资料中未找到当前会话；旧摘要已保留，请重新选择数据。')
                return
            self.provider = provider
            for sid in self.session_filter_data:
                source_messages = provider.messages(sid)
                self.session_filter_data[sid] = self.session_filter_metadata(source_messages)
                local = self.simulated_chat_messages(sid)
                if local:
                    self.session_filter_data[sid]['latest'] = max(source_messages[-1]['发送时间'], local[-1]['发送时间'])
                self.previews[sid] = sid + " " + " ".join(m["message_text"] for m in source_messages)
            self.filter_sessions()
            self.sort_sessions()
            self._source_stamp = stamp
            self.chat.set_messages(messages + self.simulated_chat_messages(session))
            pane = self.facts.handover
            pane.provider = provider
            pane.refresh_pending()
            risk = assess(provider.get_case(session, messages[-1]['发送时间']))
            self.result = run_case(provider, session, messages[-1]['发送时间'])
            self.facts.refresh_business(self.result, provider)
            self.stale_drafts.add(session)
            self.reply_button.setEnabled(False)
            self.source_label.setText('资料已变化，请清空后重新输入，或重新生成建议后核对。')
            self.risk_badge.setText(risk['level'] + ' · 新资料待核实')
            self.risk_badge.setProperty("level", risk['level'])
            self.risk_badge.style().unpolish(self.risk_badge)
            self.risk_badge.style().polish(self.risk_badge)
            if risk['level'] == 'P0':
                self.statusBar().showMessage('P0：新资料含不适或就医线索，请优先核实；无需等待摘要更新。')
            self.conversation_meta.setText(f'{len(messages)} 条历史消息 · 已载入新资料，摘要待点击更新')
        except (OSError, ValueError, KeyError):
            self.statusBar().showMessage('新资料读取失败，保留旧摘要；请检查工作簿。')

    def reset_draft(self):
        if self.result:
            if self.draft.toPlainText() and QMessageBox.question(self, '清空草稿', '清空当前未发送的文字？') != QMessageBox.StandardButton.Yes:
                return
            self.original = ''
            self.source = "人工输入"
            self.stale_drafts.discard(self.result['case']['session_id'])
            self.draft_fingerprint = json.dumps(self.result['case'], sort_keys=True)
            self.draft.clear()
            self.source_label.setText("草稿自动保存 · 仅本地模拟发送")

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
        if not self.result or not self.draft.toPlainText().strip():
            return
        session = self.result["case"]["session_id"]
        if session in self.stale_drafts:
            return
        self.reply_button.setEnabled(False)
        try:
            self.store.send_composed(scope=self.draft_scope(), session=session, token=self.send_token,
                original=self.original, edited=self.draft.toPlainText(), source=self.source,
                cutoff=self.result['case']['cutoff'], risk=self.result['risk'], operator=getpass.getuser())
        except (ValueError, sqlite3.Error, OSError):
            self.source_label.setText('模拟发送失败，原文已保留，请重试。')
            self.update_send_button()
            return
        self.original, self.source = '', '人工输入'
        self.draft.clear()
        self.draft_revision += 1
        self.source_label.setText('已本地模拟发送 · 未送达外部渠道')
        self.chat.set_messages(self.provider.messages(session) + self.simulated_chat_messages(session))
        self.session_filter_data[session]['latest'] = max(m['发送时间'] for m in self.chat.messages)
        self.sort_sessions()
        self.refresh_board()

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
        try:
            tasks = self.reports.reports()
        except (sqlite3.Error, OSError):
            self.statusBar().showMessage('上报列表读取失败，请稍后刷新。')
            return
        statuses = {}
        for report in tasks:
            statuses.setdefault(report['session'], set()).add(report['status'])
        if statuses != getattr(self, 'session_report_statuses', None):
            self.session_report_statuses = statuses
            self.filter_sessions()
        selected = self.task_list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole)['id'] if selected else None
        pending = [t for t in tasks if t["status"] in {"待处理", "处理中"}]
        self.board_nav.setText("主任" + (f" · {len(pending)}" if pending else ""))
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
            for index in range(self.task_list.count()):
                if self.task_list.item(index).data(Qt.ItemDataRole.UserRole)['id'] == selected_id:
                    self.task_list.setCurrentRow(index)
                    break
        has_tasks = self.task_list.count() > 0
        self.task_list.setVisible(has_tasks)
        self.empty_tasks.setVisible(not has_tasks)
        self.task_action.setEnabled(has_tasks)

    def edit_task(self, *_):
        item = self.task_list.currentItem()
        if item:
            HandleReportDialog(self, item.data(Qt.ItemDataRole.UserRole)).exec()
            self.refresh_board()

    def report_messages(self):
        if self.result:
            ReportDialog(self).exec()

    def browse_all_chats(self):
        AllChatsDialog(self).exec()

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
        stat = provider.source.stat()
        self._source_stamp = (stat.st_mtime_ns, stat.st_size)
        self.drafts.clear()
        self.stale_drafts.clear()
        self.populate_sessions()
        self.statusBar().showMessage("已载入业务数据：" + path)

    def configure_model(self):
        from desktop.model_settings import configure_model
        configure_model(self)

    def generate_model(self):
        if not self.result or (self.worker and self.worker.isRunning()):
            return
        config = ModelConfig(self.settings.get("base_url", ""), self.settings.get("model", ""), self.api_key)
        try:
            config.validate()
            summary = self.facts.handover.reply_summary()
        except ValueError as exc:
            QMessageBox.information(self, "请先核对", str(exc))
            return
        self.model_context_session = self.result["case"]["session_id"]
        self.model_input = json.dumps(self.result['case'], sort_keys=True)
        self.model_draft = self.draft.toPlainText()
        self.model_revision = self.draft_revision
        self.model_messages = self.store.simulated_messages(self.model_context_session)
        self.model_summary_fingerprint = digest(summary)
        self.model_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.model_button.setText('正在生成…')
        self.statusBar().showMessage("正在生成模型建议…")
        local_context = () if getattr(self.provider, 'includes_local_replies', False) else self.model_messages
        self.worker = ModelWorker(self.result, config, self, self.model_draft, local_context, summary)
        self.worker.result_ready.connect(self.model_completed)
        self.worker.finished.connect(self.model_finished)
        self.worker.start()

    def model_completed(self, output):
        if not self.result or self.result['case']['session_id'] != self.model_context_session:
            self.statusBar().showMessage('已切换会话，未填入旧会话的 AI 建议；可切回后重新生成。')
            return
        if output['status'] != 'model':
            self.source_label.setText('生成失败，请重试；原文已保留，也可直接手写回复。')
            return
        if self.model_input != json.dumps(self.result['case'], sort_keys=True):
            self.source_label.setText('生成期间资料已变化，未采用旧结果，请重新生成。')
            return
        if self.model_messages != self.store.simulated_messages(self.model_context_session):
            self.source_label.setText('生成期间已有新回复发送，未采用旧建议，请重新生成。')
            return
        try:
            current_summary = self.facts.handover.reply_summary()
        except ValueError:
            self.statusBar().showMessage('生成期间摘要已变化或需要复核，未采用旧建议。')
            return
        if digest(current_summary) != self.model_summary_fingerprint:
            self.statusBar().showMessage('生成期间摘要或人工纠正已变化，未采用旧建议，请重新生成。')
            return
        if self.model_draft or self.draft_revision != self.model_revision or self.draft.toPlainText():
            # The preview is only useful while its supporting handover is current.
            revision = self.draft_revision
            if not self.preview_suggestion(output['text']):
                return
            if revision != self.draft_revision or self.model_input != json.dumps(self.result['case'], sort_keys=True):
                self.source_label.setText('预览期间内容已变化，原文已保留，请重新生成。')
                return
            try:
                if digest(self.facts.handover.reply_summary()) != self.model_summary_fingerprint:
                    raise ValueError('summary changed')
            except ValueError:
                self.source_label.setText('预览期间摘要已变化，原文已保留，请重新生成。')
                return
        self.stale_drafts.discard(self.result['case']['session_id'])
        self.draft_fingerprint = self.model_input
        self.original = output['text']
        self.source = 'AI 建议'
        self.draft.setPlainText(self.original)
        self.remember_draft()
        self.source_label.setText('AI 建议 · 可直接修改后模拟发送 · 草稿已保存')

    def preview_suggestion(self, text):
        dialog = QDialog(self)
        dialog.setWindowTitle('预览 AI 建议')
        dialog.resize(620, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('原文已保留，点击“替换”才会更新回复框。', 'muted'))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(text)
        layout.addWidget(preview)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        controls.addButton('替换', QDialogButtonBox.ButtonRole.AcceptRole)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def model_finished(self):
        self.model_button.setEnabled(self.provider is not None)
        self.report_button.setEnabled(self.provider is not None)
        self.model_button.setText('✧  AI 建议')
        self.open_button.setEnabled(True)
        self.update_send_button()

    def closeEvent(self, event):
        if (self.worker and self.worker.isRunning()) or (self.summary_worker and self.summary_worker.isRunning()):
            self.statusBar().showMessage("模型请求仍在进行，请等待返回后关闭。")
            event.ignore()
            return
        try:
            self.remember_draft()
        except (OSError, sqlite3.Error):
            self.source_label.setText('草稿保存失败，请复制回复文字后重试关闭。')
            event.ignore()
            return
        self.source_timer.stop()
        self.report_timer.stop()
        event.accept()
