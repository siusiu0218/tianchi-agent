"""Selectable, content-sized text with native Qt line spacing."""
import math

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser


class BodyText(QTextBrowser):
    """Plain source messages stay literal; trusted summary markup is opt-in."""

    def __init__(self, value='', parent=None):
        super().__init__(parent)
        self._value = ''
        self._format = Qt.TextFormat.PlainText
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(0)
        self.setText(value)

    def text(self):
        return self._value

    def textFormat(self):
        return self._format

    def setTextFormat(self, value):
        self._format = value

    def setText(self, value):
        self._value = str(value)
        if self._format == Qt.TextFormat.RichText:
            self.setHtml(self._value)
        else:
            self.setPlainText(self._value)
        self._space_lines()

    def _space_lines(self):
        # FixedHeight tracks the actual font size, including workbench zoom.
        pixels = self.font().pixelSize()
        if pixels <= 0:
            pixels = self.fontMetrics().height() * .75
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        message = self.objectName() == 'message'
        block.setLineHeight(round(pixels * 24 / (15 if message else 14)),
                            QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        block.setTopMargin(0)
        block.setBottomMargin(0)
        cursor.mergeBlockFormat(block)
        font = QFont(self.font())
        if self.objectName() == 'summaryBody':
            # Merge spacing alone so evidence emphasis and negation stay intact.
            spacing = .5 * pixels / 14
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
            characters = QTextCharFormat()
            characters.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
            characters.setFontLetterSpacing(spacing)
            cursor.mergeCharFormat(characters)
        self.document().setDefaultFont(font)
        self._fit_height()

    def heightForWidth(self, width):
        document = self.document().clone()
        document.setTextWidth(max(1, width))
        height = math.ceil(document.size().height()) + 2
        document.deleteLater()
        return height

    def sizeHint(self):
        return QSize(0, self.heightForWidth(max(1, self.viewport().width())))

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height() + 2)

    def _fit_height(self):
        self.setFixedHeight(self.heightForWidth(max(1, self.viewport().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, '_value'):
            self._space_lines()

    def wheelEvent(self, event):
        # The surrounding chat/summary pane owns scrolling.
        event.ignore()
