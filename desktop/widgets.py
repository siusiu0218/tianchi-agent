"""Native conversation, evidence and list components; all customer text stays plain."""
from PySide6.QtCore import Qt, QSize, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QStyledItemDelegate, QStyle, QVBoxLayout, QWidget, QToolButton,
)


def text(value, name="", selectable=False):
    widget = QLabel(str(value))
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def navigation_button(title, kind, callback):
    """Small original line icons, drawn at high resolution for high-DPI displays."""
    pixmap = QPixmap(72, 72)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    pen = QPen(QColor("#c4d1e7"), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if kind == "inbox":
        painter.drawRoundedRect(QRectF(3, 4, 18, 15), 3, 3)
        painter.drawLine(3, 12, 8, 12)
        painter.drawLine(8, 12, 10, 15)
        painter.drawLine(10, 15, 14, 15)
        painter.drawLine(14, 15, 16, 12)
        painter.drawLine(16, 12, 21, 12)
    elif kind == "board":
        for x, y, height in [(4, 12, 8), (10, 4, 16), (16, 8, 12)]:
            painter.drawRoundedRect(QRectF(x, y, 4, height), 1, 1)
    else:
        painter.drawEllipse(QRectF(5, 5, 14, 14))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        for _ in range(8):
            painter.drawLine(12, 2, 12, 4)
            painter.translate(12, 12)
            painter.rotate(45)
            painter.translate(-12, -12)
    painter.end()
    result = QToolButton()
    result.setText(title)
    result.setIcon(QIcon(pixmap))
    result.setIconSize(QSize(23, 23))
    result.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    result.setObjectName("nav")
    result.setFixedSize(58, 66)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    return result


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class MessageRow(QWidget):
    def __init__(self, message):
        super().__init__()
        self.message = message
        self.outgoing = message["角色"] != "买家"
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.avatar = text("服" if self.outgoing else "客", "agentAvatar" if self.outgoing else "avatar")
        self.avatar.setFixedSize(30, 30)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bubble = QFrame()
        self.bubble.setObjectName("bubbleOut" if self.outgoing else "bubbleIn")
        content = QVBoxLayout(self.bubble)
        content.setContentsMargins(13, 10, 13, 9)
        content.setSpacing(6)
        self.body = text(message["message_text"], "message", True)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        content.addWidget(self.body)
        self.image_notice = None
        if message.get("image_path") or message.get("内容类型") == "图片":
            self.image_notice = text("▧  图片消息 · 暂不可查看", "muted")
            content.addWidget(self.image_notice)
        self.meta = text(f"{'客服' if self.outgoing else '客户'}  ·  {message['发送时间'][11:16]}", "messageMeta")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight if self.outgoing else Qt.AlignmentFlag.AlignLeft)
        content.addWidget(self.meta)
        if self.outgoing:
            row.addStretch()
            row.addWidget(self.bubble)
            row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(self.bubble)
            row.addStretch()

    def fit_width(self, available):
        maximum = max(100, min(510, int((available - 40) * .76)))
        natural = max(self.body.fontMetrics().horizontalAdvance(line) for line in self.body.text().split("\n")) + 30
        if self.image_notice:
            natural = max(natural, 225)
        width = min(maximum, max(112, natural))
        self.bubble.setFixedWidth(width)
        body_height = self.body.heightForWidth(max(1, width - 28))
        self.body.setFixedHeight(max(self.body.fontMetrics().height(), body_height))
        self.bubble.layout().activate()
        self.setFixedHeight(self.bubble.sizeHint().height())


class ChatFeed(QScrollArea):
    """All messages remain available; initial position is the end, with natural bubbles."""
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.flow = QVBoxLayout(self.canvas)
        self.flow.setContentsMargins(18, 14, 18, 18)
        self.flow.setSpacing(14)
        self.flow.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.canvas)
        self.messages = []
        self.rows = []
        self._scroll_to_end = False
        self._following_end = True
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.reflow)
        self._end_timer = QTimer(self)
        self._end_timer.setSingleShot(True)
        self._end_timer.timeout.connect(self.scroll_to_end)
        self.verticalScrollBar().rangeChanged.connect(self.range_changed)
        self.verticalScrollBar().valueChanged.connect(self.position_changed)
        self.verticalScrollBar().sliderPressed.connect(self.stop_following)
        self.show_empty()

    def show_empty(self):
        clear_layout(self.flow)
        empty = text("选择一段会话，开始有依据的沟通", "muted")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flow.addWidget(empty)

    def set_messages(self, messages):
        clear_layout(self.flow)
        self.messages = list(messages)
        self.rows = []
        last_day = None
        for message in messages:
            day = message["发送时间"][:10]
            if day != last_day:
                divider = text(day.replace("-", " / "), "date")
                divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.flow.addWidget(divider, 0, Qt.AlignmentFlag.AlignHCenter)
                last_day = day
            row = MessageRow(message)
            self.rows.append(row)
            self.flow.addWidget(row)
        self._scroll_to_end = True
        self._following_end = True
        self.reflow()
        self._layout_timer.start(30)

    def reflow(self):
        for row in self.rows:
            row.fit_width(self.viewport().width() - 36)
        self.flow.activate()
        if self._scroll_to_end:
            self._end_timer.start(40)

    def scroll_to_end(self):
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        self._scroll_to_end = False
        self._following_end = True

    def range_changed(self, minimum, maximum):
        if self._following_end:
            self._scroll_to_end = True
            self._end_timer.start(40)

    def position_changed(self, value):
        if not self._scroll_to_end:
            self._following_end = self.verticalScrollBar().maximum() - value <= 3

    def stop_following(self):
        self._following_end = False
        self._scroll_to_end = False
        self._end_timer.stop()

    def wheelEvent(self, event):
        self.stop_following()
        super().wheelEvent(event)
        self.position_changed(self.verticalScrollBar().value())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_layout_timer"):
            self._scroll_to_end = self._scroll_to_end or self._following_end
            self._layout_timer.start(30)

    def toPlainText(self):
        return "\n".join(message["message_text"] for message in self.messages)


class SessionDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(190, 62)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#edf2ff" if selected else "#f7f9fd" if hover else "#ffffff"))
        painter.drawRoundedRect(r, 9, 9)
        if selected:
            painter.setBrush(QColor("#607ce7"))
            painter.drawRoundedRect(QRectF(r.left(), r.top() + 9, 3, 38), 1.5, 1.5)
        meta = index.data(Qt.ItemDataRole.UserRole + 1) or {}
        avatar = QRectF(r.left() + 9, r.top() + 10, 26, 26)
        painter.setBrush(QColor("#dfe8ff" if selected else "#eff2f7"))
        painter.drawRoundedRect(avatar, 12, 12)
        painter.setPen(QColor("#617db3"))
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, "客")
        x = r.left() + 43
        width = r.right() - x - 10
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#2d3b52"))
        painter.drawText(QRectF(x, r.top() + 7, width, 20), Qt.AlignmentFlag.AlignLeft, str(index.data(Qt.ItemDataRole.UserRole)))
        font.setBold(False)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#8290a5"))
        painter.drawText(QRectF(x, r.top() + 31, width, 20), Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(meta.get("preview", ""), Qt.TextElideMode.ElideRight, int(width)))
        painter.setPen(QColor("#a0abba"))
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(QRectF(r.right() - 43, r.top() + 9, 38, 15), Qt.AlignmentFlag.AlignRight,
                         meta.get("date", "")[5:])
        painter.restore()


class EvidencePanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.flow = QVBoxLayout(self.canvas)
        self.flow.setContentsMargins(4, 0, 10, 12)
        self.flow.setSpacing(14)
        self.flow.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.canvas)

    def add_records(self, title, rows, folded=False):
        section = QWidget(self.canvas)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QPushButton(("▸  " if folded else "▾  ") + title)
        heading.setObjectName("fold")
        heading.setCheckable(True)
        heading.setChecked(not folded)
        layout.addWidget(heading)
        # Parent before changing visibility; an unparented visible QWidget is a window.
        body = QWidget(section)
        fields = QVBoxLayout(body)
        fields.setContentsMargins(1, 0, 1, 2)
        fields.setSpacing(8)
        if not rows:
            fields.addWidget(text("暂无记录", "muted"))
        for row in rows:
            for key, value in row.items():
                fields.addWidget(text(key, "section"))
                fields.addWidget(text(value or "暂无", selectable=True))
        layout.addWidget(body)
        body.setVisible(not folded)
        heading.toggled.connect(body.setVisible)
        heading.toggled.connect(lambda checked: heading.setText(("▾  " if checked else "▸  ") + title))
        self.flow.addWidget(section)

    def show_result(self, result, provider):
        clear_layout(self.flow)
        case = result["case"]
        if getattr(self, "state_path", None):
            from desktop.handover import HandoverPane
            self.handover = HandoverPane(provider, self.state_path, case["session_id"], self.canvas)
            self.flow.addWidget(self.handover)
        primary_flow = self.flow
        business = QWidget(self.canvas)
        self.business_flow = QVBoxLayout(business)
        self.business_flow.setContentsMargins(0, 0, 0, 0)
        self.business_flow.setSpacing(4)
        toggle = QPushButton('▸  订单、工单与物流', self.canvas)
        toggle.setObjectName('fold')
        toggle.setCheckable(True)
        toggle.toggled.connect(business.setVisible)
        toggle.toggled.connect(lambda yes: toggle.setText(('▾  ' if yes else '▸  ') + '订单、工单与物流'))
        primary_flow.addWidget(toggle)
        primary_flow.addWidget(business)
        business.hide()
        self.refresh_business(result, provider)
        self.verticalScrollBar().setValue(0)

    def refresh_business(self, result, provider):
        """Refresh live snapshots without replacing the summary being reviewed."""
        primary_flow = self.flow
        self.flow = self.business_flow
        clear_layout(self.flow)
        case = result['case']
        self.add_records("关联订单", case["orders"], folded=True)
        self.add_records(f"已创建工单  ·  {len(case['tickets'])}", case["tickets"], folded=True)
        if result["service"]:
            self.add_records("物流与换货", [{"建议下一步": result["service"]["next_step"],
                                            "图片证据": result["service"]["image_notice"]}], folded=True)
            shipping = provider.logistics_snapshot(case["session_id"])
            self.add_records("原订单物流快照", shipping["original"], folded=True)
            self.add_records("补发物流快照", shipping["replacement"], folded=True)
        self.add_records("完整工单快照 · 仅供核对", provider.ticket_snapshot(case["session_id"]), folded=True)
        self.flow.addWidget(text("快照仅供核对；物流单号不代表已经发货。", "muted"))
        self.flow = primary_flow


class MetricCard(QFrame):
    def __init__(self, title, hint, color):
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(5)
        layout.addWidget(text(title, "section"))
        self.number = text("0", "metricNumber")
        self.number.setStyleSheet(f"color: {color};")
        layout.addWidget(self.number)
        layout.addWidget(text(hint, "muted"))


class TaskDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(600, 86)

    def paint(self, painter, option, index):
        import json
        task = index.data(Qt.ItemDataRole.UserRole)
        if not task:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect.adjusted(2, 3, -2, -3)
        painter.setPen(QPen(QColor("#dce5fa")))
        painter.setBrush(QColor("#f0f4ff" if option.state & QStyle.StateFlag.State_Selected else "#ffffff"))
        painter.drawRoundedRect(r, 9, 9)
        level = json.loads(task["payload"])["risk"]["level"]
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#34435b"))
        painter.drawText(r.adjusted(20, 15, -20, -35), Qt.AlignmentFlag.AlignLeft, task["session"])
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#8290a5"))
        subtitle = f"负责人 {task['owner']}   ·   更新于 {task['updated'][:16].replace('T', ' ')} UTC"
        painter.drawText(r.adjusted(20, 43, -190, -10), Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, max(1, r.width() - 210)))
        painter.setPen(QColor("#b24b61" if level == "P0" else "#9c7b35"))
        painter.drawText(r.adjusted(r.width() - 170, 27, -115, -15), Qt.AlignmentFlag.AlignCenter, level)
        painter.setPen(QColor("#5575b3"))
        painter.drawText(r.adjusted(r.width() - 110, 27, -15, -15), Qt.AlignmentFlag.AlignCenter, task["status"])
        if index.data(Qt.ItemDataRole.UserRole + 1):
            painter.setPen(QColor("#b78a40"))
            painter.drawText(r.adjusted(r.width() - 235, 27, -175, -15), Qt.AlignmentFlag.AlignCenter, "已超时")
        painter.restore()
