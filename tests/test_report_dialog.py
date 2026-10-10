"""Real mouse and keyboard reporting interactions against isolated records."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from copilot.data import DEFAULT_SOURCE, ExcelProvider
from copilot.reports import ReportStore
from copilot.store import ReviewStore
from desktop.reporting import ReportDialog
from desktop.theme import STYLE


class ReportParent(QMainWindow):
    def simulated_chat_messages(self, session):
        return []

    def refresh_board(self):
        self.refreshed = True


class ReportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.provider = ExcelProvider(DEFAULT_SOURCE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = ReportParent()
        self.parent.setStyleSheet(STYLE)
        self.parent.provider = self.provider
        self.parent.reports = ReportStore(ReviewStore(Path(self.temp.name) / 'reviews.sqlite3'))
        self.parent.result = {'case': {'session_id': 'S00268'}, 'risk': {'level': 'P0'}}
        self.dialog = ReportDialog(self.parent)
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.parent.close()
        self.dialog.deleteLater()
        self.parent.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def click_text(self):
        rect = self.dialog.selection.visualItemRect(self.dialog.selection.item(0))
        QTest.mouseClick(self.dialog.selection.viewport(), Qt.LeftButton,
                         pos=QPoint(rect.x() + 90, rect.center().y()))
        self.app.processEvents()

    def test_text_click_checks_without_hiding_original_and_can_cancel(self):
        item = self.dialog.selection.item(0)
        original = item.text()
        self.click_text()
        self.assertEqual(item.checkState(), Qt.Checked)
        self.assertFalse(item.isSelected())
        self.assertEqual(item.text(), original)
        self.assertIn('已勾选 1 条', self.dialog.selection_status.text())
        self.click_text()
        self.assertEqual(item.checkState(), Qt.Unchecked)
        self.assertFalse(self.dialog.submit_button.isEnabled())

    def test_checkbox_and_space_toggle_once_each(self):
        view = self.dialog.selection
        item = view.item(0)
        row = view.itemWidget(item)
        point = row.check.mapTo(view.viewport(), row.check.rect().center())
        for expected in (Qt.Checked, Qt.Unchecked):
            QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point)
            self.assertEqual(item.checkState(), expected)
        view.setCurrentItem(item)
        view.setFocus()
        QTest.keyClick(view, Qt.Key_Space)
        self.assertEqual(item.checkState(), Qt.Checked)

    def test_drag_range_can_shrink_cancel_and_preserve_other_checks(self):
        view = self.dialog.selection
        self.dialog.resize(760, 1000)
        self.app.processEvents()
        view.item(4).setCheckState(Qt.Checked)
        points = [view.visualItemRect(view.item(i)).center() for i in range(3)]
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=points[0])
        QTest.mouseMove(view.viewport(), points[2])
        self.assertTrue(all(view.item(i).checkState() == Qt.Checked for i in range(3)))
        QTest.mouseMove(view.viewport(), points[1])
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=points[1])
        self.assertEqual([view.item(i).checkState() for i in range(3)], [Qt.Checked, Qt.Checked, Qt.Unchecked])
        self.assertEqual(view.item(4).checkState(), Qt.Checked)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=points[1])
        QTest.mouseMove(view.viewport(), points[0])
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=points[0])
        self.assertTrue(all(view.item(i).checkState() == Qt.Unchecked for i in range(3)))
        self.assertEqual(view.item(4).checkState(), Qt.Checked)
        self.assertFalse(view._scroll_timer.isActive())

    def test_drag_scroll_and_bubbles_preserve_literal_source(self):
        view = self.dialog.selection
        self.dialog.resize(760, 680)
        self.app.processEvents()
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=view.visualItemRect(view.item(0)).center())
        bottom = QPoint(100, view.viewport().height() + 10)
        QTest.mouseMove(view.viewport(), bottom)
        QTest.qWait(700)
        self.assertGreater(view.verticalScrollBar().value(), 0)
        self.assertGreater(sum(view.item(i).checkState() == Qt.Checked for i in range(view.count())), 1)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=bottom)
        value = view.verticalScrollBar().value()
        QTest.qWait(100)
        self.assertEqual(view.verticalScrollBar().value(), value)
        for i in range(view.count()):
            item = view.item(i)
            row = view.itemWidget(item)
            message = item.data(Qt.UserRole)
            self.assertEqual(row.chat.body.toPlainText(), message['message_text'])
            self.assertEqual(row.chat.outgoing, message['角色'] != '买家')
            self.assertEqual(row.check.isChecked(), item.checkState() == Qt.Checked)

    def test_submit_requires_selection_reason_and_operator_and_preserves_evidence(self):
        d = self.dialog
        self.assertFalse(d.submit_button.isEnabled())
        d.reason.setPlainText('请主任核实消费者诉求')
        self.assertFalse(d.submit_button.isEnabled())
        self.click_text()
        self.assertTrue(d.submit_button.isEnabled())
        d.operator.clear()
        self.assertFalse(d.submit_button.isEnabled())
        d.operator.setText('验收客服')
        d.reason.setPlainText('  ')
        self.assertFalse(d.submit_button.isEnabled())
        d.reason.setPlainText('请主任核实消费者诉求')
        d.submit_button.click()
        rows = self.parent.reports.reports()
        self.assertEqual(len(rows), 1)
        import json
        payload = json.loads(rows[0]['payload'])
        self.assertEqual(payload['messages'], [self.provider.messages('S00268')[0]])
        self.assertEqual(payload['risk']['level'], 'P0')
        self.assertEqual(d.result(), 1)
        self.assertTrue(self.parent.refreshed)
