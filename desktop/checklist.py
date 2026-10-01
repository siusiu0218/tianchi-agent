"""Human-controlled checklist shown in the handover and director view."""
import getpass
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)


ICON = Path(__file__).resolve().parent / 'assets' / 'ellipsis.svg'


def label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def show_screenshot(parent, store, file_row):
    path = store.screenshot_path(file_row)
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        QMessageBox.warning(parent, '截图不可用', '本地截图文件丢失或无法读取。')
        return
    dialog = QDialog(parent)
    dialog.setWindowTitle('核实截图 · ' + file_row['original_name'])
    dialog.resize(760, 580)
    layout = QVBoxLayout(dialog)
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    image = QLabel()
    image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    image.setPixmap(pixmap.scaled(1100, 850, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
    scroll.setWidget(image)
    layout.addWidget(scroll)
    layout.addWidget(label('由客服附上的本地截图；请结合原始记录核对。'))
    dialog.exec()


class ItemDialog(QDialog):
    def __init__(self, parent, evidence, current=None):
        super().__init__(parent)
        self.setWindowTitle('修改清单事项' if current else '添加清单事项')
        self.resize(520, 220)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.text = QLineEdit(current['text'] if current else '')
        self.text.setPlaceholderText('写清楚需要核实或处理的事')
        self.actor = QLineEdit(getpass.getuser())
        form.addRow('事项', self.text)
        form.addRow('操作人', self.actor)
        self.reference = QComboBox()
        self.reference.addItem('不选择记录依据', '')
        for ref, detail in evidence.items():
            excerpt = str(detail.get('原文') or detail.get('任务状态') or '')[:45]
            self.reference.addItem(ref + (' · ' + excerpt if excerpt else ''), ref)
        form.addRow('记录依据', self.reference)
        if current and current['refs']:
            self.reference.setEnabled(False)
            layout.addWidget(label('原有来源依据会保留；勾选完成后也可另附截图。'))
        layout.addLayout(form)
        self.error = label('')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ChecklistWidget(QWidget):
    def __init__(self, store, session, evidence, parent=None):
        super().__init__(parent)
        self.store, self.session, self.evidence = store, session, evidence
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(5)
        self.reload()

    def reload(self):
        while self.layout.count():
            part = self.layout.takeAt(0)
            if part.widget():
                part.widget().hide()
                part.widget().deleteLater()
        self.rows = self.store.items(self.session)
        if not self.rows:
            self.layout.addWidget(label('暂无待确认事项；客服可手动添加。'))
        for item in self.rows:
            row = QWidget(self)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(row)
            check.setObjectName('checklistDone')
            check.setChecked(bool(item['done']))
            check.setToolTip('由客服手动确认完成；可取消勾选')
            check.setFixedWidth(24)
            check.toggled.connect(lambda yes, item_id=item['id']: self.toggle(item_id, yes))
            line.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
            body = label(item['text'])
            body.setObjectName('checklistText')
            body.setToolTip('来源：' + ('、'.join(item['refs']) if item['refs'] else '人工添加'))
            line.addWidget(body, 1)
            menu_button = QToolButton(row)
            menu_button.setObjectName('checklistMenu')
            menu_button.setAccessibleName('更多操作：' + item['text'])
            menu_button.setToolTip('修改、删除或附截图')
            menu_button.setIcon(QIcon(str(ICON)))
            menu_button.setIconSize(QSize(20, 20))
            menu_button.setAutoRaise(True)
            menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(menu_button)
            menu.addAction('修改', lambda item_id=item['id']: self.edit(item_id))
            menu.addAction('删除', lambda item_id=item['id']: self.delete(item_id))
            menu.addAction('附截图', lambda item_id=item['id']: self.attach(item_id))
            menu_button.setMenu(menu)
            line.addWidget(menu_button, 0, Qt.AlignmentFlag.AlignTop)
            self.layout.addWidget(row)
            if item['done'] and item['completion_event']:
                event = item['completion_event']
                done_label = label('已由 ' + event['actor'] + ' 勾选 · '
                                   + event['created'][:19].replace('T', ' ') + ' UTC · 依据：'
                                   + (item['completion_ref'] or '客服附图'))
                done_label.setObjectName('muted')
                self.layout.addWidget(done_label)
            for file_row in item['files']:
                view = QPushButton('查看截图 · ' + file_row['original_name'], self)
                view.setObjectName('checklistFile')
                view.setFlat(True)
                view.clicked.connect(lambda checked=False, f=file_row: show_screenshot(self, self.store, f))
                self.layout.addWidget(view)
        add = QPushButton('＋ 添加一项', self)
        add.setObjectName('checklistAdd')
        add.setFlat(True)
        add.clicked.connect(self.add)
        self.layout.addWidget(add)

    def toggle(self, item_id, yes):
        completion_ref = ''
        if yes:
            current = next(item for item in self.rows if item['id'] == item_id)
            choices = [('截图：' + file_row['original_name'], '本地截图')
                       for file_row in current['files']]
            choices.extend((ref, str(detail.get('原文') or detail.get('任务状态') or '')[:55])
                           for ref, detail in self.evidence.items())
            if not choices:
                QMessageBox.information(self, '缺少完成依据', '请先附上截图，或等待可引用的业务记录。')
                self.reload()
                return
            labels = [ref + (' · ' + preview if preview else '') for ref, preview in choices]
            selected, accepted = QInputDialog.getItem(self, '选择完成依据',
                '请选择能证明该项已经核实或处理的记录；原清单来源只说明为什么需要核实。',
                labels, 0, False)
            if not accepted:
                self.reload()
                return
            completion_ref = choices[labels.index(selected)][0]
        try:
            self.store.set_done(item_id, yes, getpass.getuser(), completion_ref)
        except ValueError as exc:
            QMessageBox.information(self, '暂不能完成', str(exc))
        self.reload()

    def add(self):
        dialog = ItemDialog(self, self.evidence)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ref = dialog.reference.currentData()
            self.store.add(self.session, dialog.text.text(), dialog.actor.text(), [ref] if ref else [])
        except ValueError as exc:
            QMessageBox.information(self, '未添加', str(exc))
            return
        self.reload()

    def edit(self, item_id):
        current = next(item for item in self.rows if item['id'] == item_id)
        dialog = ItemDialog(self, self.evidence, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ref = dialog.reference.currentData()
            refs = current['refs'] or ([ref] if ref else [])
            self.store.edit(item_id, dialog.text.text(), dialog.actor.text(), refs)
        except ValueError as exc:
            QMessageBox.information(self, '未修改', str(exc))
            return
        self.reload()

    def delete(self, item_id):
        if QMessageBox.question(self, '删除事项', '删除这条清单事项？操作记录仍会保留。') != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(item_id, getpass.getuser())
        self.reload()

    def attach(self, item_id):
        path, _ = QFileDialog.getOpenFileName(self, '选择核实截图', '',
                                               '图片 (*.png *.jpg *.jpeg *.webp)')
        if not path:
            return
        try:
            self.store.attach(item_id, path, getpass.getuser())
        except ValueError as exc:
            QMessageBox.information(self, '未附截图', str(exc))
            return
        self.reload()


class ReadOnlyChecklist(QWidget):
    def __init__(self, store, session, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        rows = store.items(session)
        layout.addWidget(label('客服处理清单（仅查看）'))
        if not rows:
            layout.addWidget(label('暂无清单事项。'))
        for item in rows:
            mark = '☑' if item['done'] else '☐'
            entry = label(mark + ' ' + item['text'])
            entry.setToolTip('建议来源：' + ('、'.join(item['refs']) if item['refs'] else '人工添加')
                             + ('\n完成依据：' + (item['completion_ref'] or '客服附图') if item['done'] else ''))
            layout.addWidget(entry)
            if item['done']:
                event = item['completion_event'] or {}
                layout.addWidget(label('由 ' + event.get('actor', '客服') + ' 勾选 · '
                                       + event.get('created', '')[:19].replace('T', ' ')
                                       + ' UTC · 完成依据：' + (item['completion_ref'] or '客服附图')))
            for file_row in item['files']:
                button = QPushButton('查看截图 · ' + file_row['original_name'])
                button.setFlat(True)
                button.clicked.connect(lambda checked=False, f=file_row: show_screenshot(self, store, f))
                layout.addWidget(button)
