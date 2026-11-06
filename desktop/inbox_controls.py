"""Compact inbox menus retaining native mouse and keyboard navigation."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QColor

from desktop.controls import SoftMenu


class InboxMenu(SoftMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('inboxMenu')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        factor = self.parent().window().zoom_percent / 100
        painter.setPen(QPen(QColor('#262626'), 1.8 * factor,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        for action in self.actions():
            if action.isChecked() and action.isVisible():
                rect = self.actionGeometry(action)
                x, y = rect.right() - 18 * factor, rect.center().y()
                painter.drawLine(QPointF(x - 5 * factor, y), QPointF(x - factor, y + 4 * factor))
                painter.drawLine(QPointF(x - factor, y + 4 * factor), QPointF(x + 6 * factor, y - 4 * factor))
        painter.end()
