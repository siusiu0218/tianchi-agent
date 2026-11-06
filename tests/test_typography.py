"""Reading layout preserves source text, copy, and zoom without clipping."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtTest import QTest

from desktop.theme import STYLE, scaled_style
from desktop.typography import BodyText


class TypographyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reflow_copy_and_zoom_keep_literal_source(self):
        window = QWidget()
        window.setStyleSheet(STYLE)
        layout = QVBoxLayout(window)
        source = '<b>原文</b> AI，订单 S00268：\n' + '这是需要完整显示的中文消息。' * 20
        body = BodyText(source)
        body.setObjectName('message')
        layout.addWidget(body)
        window.resize(420, 300)
        window.show()
        QTest.qWait(80)
        self.assertEqual(body.toPlainText(), source)
        self.assertEqual(body.document().firstBlock().blockFormat().lineHeight(), 24)
        normal = body.heightForWidth(260)
        self.assertGreater(normal, body.heightForWidth(380))
        self.assertGreaterEqual(body.height(), body.heightForWidth(body.viewport().width()))
        cursor = body.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        body.setTextCursor(cursor)
        previous_clipboard = self.app.clipboard().text()
        body.copy()
        self.assertEqual(self.app.clipboard().text(), source)
        self.app.clipboard().setText(previous_clipboard)
        window.setStyleSheet(scaled_style(130))
        QTest.qWait(80)
        self.assertGreater(body.document().firstBlock().blockFormat().lineHeight(), 24)
        self.assertGreater(body.heightForWidth(260), normal)
        self.assertEqual(body.toPlainText(), source)
        window.close()
        window.deleteLater()

    def test_summary_spacing_preserves_emphasis_and_negation(self):
        window = QWidget()
        window.setStyleSheet(STYLE)
        layout = QVBoxLayout(window)
        body = BodyText()
        body.setObjectName('summaryBody')
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setText('消费者<b>尚未就医</b>，希望换货。<br>' + '需核实原始记录。' * 12)
        layout.addWidget(body)
        window.resize(340, 320)
        window.show()
        QTest.qWait(80)
        self.assertIn('消费者尚未就医，希望换货。', body.toPlainText())
        cursor = body.document().find('尚未就医')
        self.assertGreaterEqual(cursor.charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertAlmostEqual(cursor.charFormat().fontLetterSpacing(), .5)
        self.assertGreaterEqual(body.height(), body.heightForWidth(body.viewport().width()))
        original = body.toPlainText()
        window.setStyleSheet(scaled_style(130))
        QTest.qWait(80)
        self.assertEqual(body.toPlainText(), original)
        self.assertGreater(body.document().find('尚未就医').charFormat().fontLetterSpacing(), .5)
        window.close()
        window.deleteLater()
