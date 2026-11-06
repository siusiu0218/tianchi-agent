"""Chat bubbles with explicit click/drag selection for local staff reports."""
from PySide6.QtCore import Qt, QTimer, QSize, QPoint, QEvent
from PySide6.QtWidgets import QListWidget, QWidget, QHBoxLayout, QCheckBox, QStyledItemDelegate

from desktop.widgets import MessageRow


class BubbleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # The embedded row paints the full item; do not repeat its source text.
        pass

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class ReportMessageRow(QWidget):
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setObjectName('reportMessageRow')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # The list owns the gesture, including presses on bubble text or avatars.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        self.check = QCheckBox()
        self.check.setObjectName('reportPick')
        self.check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chat = MessageRow(message)
        self.chat.meta.setText(f"{message['角色']} · {message['发送时间']}")
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.chat, 1)
        self.set_checked(False)

    def set_checked(self, checked):
        self.check.setChecked(checked)
        self.setProperty('reportedSelected', checked)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def fit_width(self, width, factor):
        self.layout().setContentsMargins(round(10 * factor), round(10 * factor), round(12 * factor), round(10 * factor))
        self.layout().setSpacing(round(14 * factor))
        self.chat.set_zoom(factor)
        self.chat.fit_width(max(80, width - round(60 * factor)))
        return QSize(width, self.chat.height() + round(20 * factor))


class MessageSelection(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(BubbleDelegate(self))
        self._anchor = None
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._drag_position = QPoint()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(45)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        self.itemChanged.connect(self._sync_row)

    def add_message(self, item):
        self.addItem(item)
        self.setItemWidget(item, ReportMessageRow(item.data(Qt.ItemDataRole.UserRole), self))
        self.reflow()

    def _sync_row(self, item):
        row = self.itemWidget(item)
        if row:
            row.set_checked(item.checkState() == Qt.CheckState.Checked)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or item is None:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self.setCurrentItem(item)
        self._anchor = self.row(item)
        self._before = [self.item(i).checkState() for i in range(self.count())]
        self._target = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        self._drag_position = event.position().toPoint()
        self._apply_range(self._anchor)
        self._scroll_timer.start()
        event.accept()

    def _apply_range(self, end):
        start, stop = sorted((self._anchor, end))
        for i, previous in enumerate(self._before):
            state = self._target if start <= i <= stop else previous
            if self.item(i).checkState() != state:
                self.item(i).setCheckState(state)

    def _update_range(self):
        point = QPoint(max(0, min(self.viewport().width() - 1, self._drag_position.x())),
                       max(0, min(self.viewport().height() - 1, self._drag_position.y())))
        item = self.itemAt(point)
        if item:
            self._apply_range(self.row(item))

    def mouseMoveEvent(self, event):
        if self._anchor is None:
            super().mouseMoveEvent(event)
            return
        self._drag_position = event.position().toPoint()
        self._update_range()
        event.accept()

    def _auto_scroll(self):
        if self._anchor is None:
            return
        y = self._drag_position.y()
        step = -18 if y < 24 else 18 if y > self.viewport().height() - 24 else 0
        if step:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + step)
            self._update_range()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._anchor is not None:
            self._drag_position = event.position().toPoint()
            self._update_range()
            self._anchor = None
            self._scroll_timer.stop()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        self._anchor = None
        self._scroll_timer.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.currentItem():
            item = self.currentItem()
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def reflow(self):
        width = max(100, self.viewport().width())
        factor = max(.5, self.font().pixelSize() / 14)
        for i in range(self.count()):
            item = self.item(i)
            row = self.itemWidget(item)
            if row:
                item.setSizeHint(row.fit_width(width, factor))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            QTimer.singleShot(0, self.reflow)
