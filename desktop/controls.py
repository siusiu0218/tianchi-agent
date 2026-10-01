"""Shared selection controls with a soft, keyboard-accessible popup."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QComboBox, QFrame, QListView, QStyledItemDelegate, QMenu


class SoftMenu(QMenu):
    def showEvent(self, event):
        super().showEvent(event)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(outline.toFillPolygon().toPolygon()))


class SoftComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView()
        view.setObjectName("selectOptions")
        view.setSpacing(3)
        view.setMouseTracking(True)
        view.setItemDelegate(QStyledItemDelegate(view))
        self.setView(view)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaxVisibleItems(10)

    def showPopup(self):
        popup = self.view().window()
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.setObjectName("selectPopup")
        if isinstance(popup, QFrame):
            popup.setFrameShape(QFrame.Shape.NoFrame)
        super().showPopup()
        # Clip the native popup window as well as its styled list surface.
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(popup.rect()), 12, 12)
        popup.setMask(QRegion(outline.toFillPolygon().toPolygon()))
