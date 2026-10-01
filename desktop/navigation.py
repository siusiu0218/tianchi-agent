"""Spatial sidebar and message navigation for the inbox."""
from html import escape

from PySide6.QtCore import Qt, QSize, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QSplitter, QSplitterHandle, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QWidget,
)


class SessionItem(QListWidgetItem):
    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole + 2) < other.data(Qt.ItemDataRole.UserRole + 2)


class SlidingPanel(QWidget):
    """Clip a full-width panel while it slides; do not squeeze its text per frame."""
    def __init__(self, content):
        super().__init__()
        self.content = content
        content.setParent(self)
        content.show()
        self.setMinimumWidth(330)
        self.expanded_width = 350
        self.animating = False
        self.motion = QVariantAnimation(self)
        self.motion.valueChanged.connect(self.frame)
        self.motion.finished.connect(self.finish)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.expanded_width if self.animating else self.width()
        self.content.setGeometry(0, 0, width, self.height())

    def slide(self, visible):
        split = self.parentWidget()
        sizes = split.sizes()
        if not self.animating and sizes[2] > 0:
            self.expanded_width = sizes[2]
        self.motion.stop()
        self.target_visible = visible
        self.animating = True
        self.setMinimumWidth(0)
        start = 0 if self.isHidden() else sizes[2]
        self.show()
        self.content.show()
        self.content.setGeometry(0, 0, self.expanded_width, self.height())
        end = self.expanded_width if visible else 0
        self.motion.setDuration(max(90, int(250 * abs(end - start) / max(1, self.expanded_width))))
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic if visible else QEasingCurve.Type.InOutCubic)
        self.motion.blockSignals(True)
        self.motion.setStartValue(start)
        self.motion.setEndValue(end)
        self.motion.blockSignals(False)
        self.frame(start)
        self.motion.start()

    def frame(self, width):
        split = self.parentWidget()
        left = split.sizes()[0]
        available = split.width() - 2 * split.handleWidth()
        split.setSizes([left, max(420, available - left - int(width)), int(width)])

    def finish(self):
        self.animating = False
        self.setVisible(self.target_visible)
        self.setMinimumWidth(330)
        self.content.setGeometry(0, 0, self.width(), self.height())


class SidebarHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("拖动调整侧栏宽度")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QColor('#8991de' if self.underMouse() or self.hasFocus() else '#e6e5ec'))
        painter.drawLine(self.width() // 2, 0, self.width() // 2, self.height())

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self is self.splitter().handle(1):
            self.splitter().toggle_list()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self is self.splitter().handle(1):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space):
                self.splitter().toggle_list()
                return
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                sizes = self.splitter().sizes()
                width = sizes[0] + (24 if event.key() == Qt.Key.Key_Right else -24)
                self.splitter().moveSplitter(max(0, width), 1)
                return
        super().keyPressEvent(event)


class InboxSplitter(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.list_width = 240
        self.setObjectName("inboxSplit")
        self.setHandleWidth(10)
        self.splitterMoved.connect(self.remember_width)

    def createHandle(self):
        return SidebarHandle(self.orientation(), self)

    def remember_width(self, *_):
        if self.sizes()[0] > 0:
            self.list_width = self.sizes()[0]

    def toggle_list(self):
        sizes = self.sizes()
        old = sizes[0]
        if old:
            self.list_width = old
        sizes[0] = 0 if old else self.list_width
        sizes[1] += old - sizes[0]
        self.setSizes(sizes)


class MessageTick(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1

    def set_zoom(self, factor):
        self.zoom_factor = factor

    def sizeHint(self, option, index):
        return QSize(round(28 * self.zoom_factor), round(16 * self.zoom_factor))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(option.rect.topLeft())
        painter.scale(self.zoom_factor, self.zoom_factor)
        active = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#5968d9' if active else '#c9cbd5'))
        width = 23 if active else (17 if index.data(Qt.ItemDataRole.UserRole + 1) else 11)
        painter.drawRoundedRect(QRectF(option.rect.width() / self.zoom_factor / 2 - width / 2,
                                       option.rect.height() / self.zoom_factor / 2 - 1.5, width, 3), 1.5, 1.5)
        painter.restore()


class MessageMap(QListWidget):
    def __init__(self, chat):
        super().__init__()
        self.chat = chat
        self.setObjectName('messageMap')
        self.setFixedWidth(30)
        self.setMouseTracking(True)
        self.setItemDelegate(MessageTick(self))
        self.setAccessibleName('消息定位：悬停预览，点击或按回车跳转原文')
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemClicked.connect(self.locate)
        self.itemActivated.connect(self.locate)
        chat.messagesChanged.connect(self.refresh)
        chat.verticalScrollBar().valueChanged.connect(self.follow_reading)

    def set_zoom(self, factor):
        self.setFixedWidth(round(30 * factor))
        self.itemDelegate().set_zoom(factor)
        self.doItemsLayout()

    def refresh(self):
        self.clear()
        for index, message in enumerate(self.chat.messages):
            role = '客户' if message['角色'] == '买家' else '客服'
            identity = str(message['message_id'])
            item = QListWidgetItem(f'{index + 1} · {role} · {message["发送时间"]} · {message["message_text"]}')
            item.setData(Qt.ItemDataRole.UserRole, identity)
            item.setData(Qt.ItemDataRole.UserRole + 1, role == '客户')
            preview = message['message_text'][:280]
            if len(message['message_text']) > 280:
                preview += '…'
            item.setToolTip('<div style="width:300px"><b>' + escape(role + ' · ' + message['发送时间']) + '</b><p>'
                            + escape(preview).replace('\n', '<br>') + '</p>' + escape(identity) + '<br>点击定位原文</div>')
            self.addItem(item)

    def locate(self, item):
        self.chat.jump_to_message(item.data(Qt.ItemDataRole.UserRole))

    def follow_reading(self, value):
        if self.hasFocus():
            return
        for index, row in enumerate(self.chat.rows):
            if row.y() + row.height() > value:
                self.setCurrentRow(index)
                self.scrollToItem(self.item(index))
                break
