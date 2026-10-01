"""Staff selection and director review of explicitly reported messages."""
import getpass
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QLineEdit, QTextEdit, QPushButton, QComboBox, QScrollArea)
from desktop.widgets import ChatFeed
from desktop.checklist import ReadOnlyChecklist
from copilot.checklist import ChecklistStore
from copilot.summary import digest


def plain(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def messages(parent, session):
    return parent.provider.messages(session) + parent.simulated_chat_messages(session)


class AllChatsDialog(QDialog):
    def __init__(self, parent, session=None):
        super().__init__(parent)
        self.setWindowTitle('主任 · 查看全部聊天')
        self.resize(850, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(plain('可查阅已载入的全部会话；查看聊天不会生成上报或提醒。'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索会话编号或消息内容')
        layout.addWidget(self.search)
        self.sessions = QComboBox()
        self.ids = parent.provider.sessions() if parent.provider else []
        self.texts = {s: s + ' ' + ' '.join(m['message_text'] for m in messages(parent, s)) for s in self.ids}
        layout.addWidget(self.sessions)
        self.chat = ChatFeed()
        layout.addWidget(self.chat, 1)
        self.sessions.currentTextChanged.connect(self.show_session)
        self.search.textChanged.connect(self.filter_sessions)
        self.filter_sessions('')
        if session:
            self.sessions.setCurrentText(session)

    def filter_sessions(self, query):
        self.sessions.clear()
        self.sessions.addItems([s for s in self.ids if query.casefold() in self.texts[s].casefold()])

    def show_session(self, session):
        self.chat.set_messages(messages(self.parent(), session) if session else [])


class MessageSelection(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(100, self.viewport().width() - 48)
        for index in range(self.count()):
            item = self.item(index)
            bounds = self.fontMetrics().boundingRect(
                QRect(0, 0, width, 100000), Qt.TextFlag.TextWordWrap, item.text())
            item.setSizeHint(QSize(width, bounds.height() + 18))


class ReportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.session = parent.result['case']['session_id']
        self.risk = parent.result['risk']
        self.token = str(uuid4())
        self.setWindowTitle('上报主任 · ' + self.session)
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(plain('勾选需要主任处理的消息，再说明原因。提交后进入主任的待处理列表。'))
        self.selection = MessageSelection()
        self.selection.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selection.setWordWrap(True)
        for message in messages(parent, self.session):
            item = QListWidgetItem(f"{message['角色']} · {message['发送时间']}\n{message['message_text']}")
            item.setData(Qt.ItemDataRole.UserRole, message)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.selection.addItem(item)
        layout.addWidget(self.selection, 1)
        layout.addWidget(plain('上报人'))
        self.operator = QLineEdit(getpass.getuser())
        layout.addWidget(self.operator)
        layout.addWidget(plain('需要主任处理什么？'))
        self.reason = QTextEdit()
        self.reason.setAcceptRichText(False)
        self.reason.setMaximumHeight(100)
        layout.addWidget(self.reason)
        self.error = plain('本地演示：尚未连接其他电脑或真实客服渠道。')
        layout.addWidget(self.error)
        self.submit_button = QPushButton('确认上报主任')
        self.submit_button.clicked.connect(self.submit)
        layout.addWidget(self.submit_button)

    def submit(self):
        chosen = [self.selection.item(i).data(Qt.ItemDataRole.UserRole)
                  for i in range(self.selection.count())
                  if self.selection.item(i).checkState() == Qt.CheckState.Checked]
        try:
            self.parent().reports.submit(token=self.token, session=self.session,
                operator=self.operator.text(), reason=self.reason.toPlainText(), messages=chosen, risk=self.risk)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        except (sqlite3.Error, OSError):
            self.error.setText('上报保存失败，内容已保留，请重试。')
            return
        self.parent().refresh_board()
        self.parent().statusBar().showMessage('已上报主任，可在主任页面查看处理进度。')
        self.accept()


class HandleReportDialog(QDialog):
    def __init__(self, parent, report):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle(f"处理上报 #{report['id']} · {report['session']}")
        self.resize(780, 750)
        layout = QVBoxLayout(self)
        layout.addWidget(plain(f"上报人：{report['operator']} · {report['created'][:19]} UTC\n上报原因：{report['reason']}"))
        self.chat = ChatFeed()
        self.chat.set_messages(json.loads(report['payload'])['messages'])
        layout.addWidget(self.chat, 1)
        full = QPushButton('查看这段会话的全部聊天')
        full.clicked.connect(lambda: AllChatsDialog(parent, report['session']).exec())
        layout.addWidget(full)
        namespace = digest(str(Path(parent.provider.source).resolve()).casefold())
        checklist = ChecklistStore(parent.store.path, namespace)
        self.checklist_rows = checklist.items(report['session'])
        checklist_scroll = QScrollArea(self)
        checklist_scroll.setWidgetResizable(True)
        checklist_scroll.setMaximumHeight(180)
        checklist_scroll.setWidget(ReadOnlyChecklist(checklist, report['session'], checklist_scroll))
        layout.addWidget(checklist_scroll)
        remaining = [item['text'] for item in self.checklist_rows if not item['done']]
        if remaining:
            layout.addWidget(plain('清单仍有未完成事项：' + '；'.join(remaining)
                                   + '。主任处理上报后，客服仍可继续核实。'))
        history = '\n'.join(f"{e['created'][:19]} UTC · {e['operator']} · {e['status']}：{e['note']}"
                            for e in parent.reports.events(report['id']))
        timeline = QTextEdit()
        timeline.setReadOnly(True)
        timeline.setPlainText(history)
        timeline.setMaximumHeight(110)
        layout.addWidget(timeline)
        self.operator = QLineEdit(getpass.getuser())
        layout.addWidget(plain('处理人'))
        layout.addWidget(self.operator)
        self.status = QComboBox()
        self.status.addItems(['处理中'] if report['status'] == '已处理' else ['处理中', '已处理'])
        layout.addWidget(self.status)
        self.note = QLineEdit()
        self.note.setPlaceholderText('填写处理说明（客服可在上报记录中查阅）')
        layout.addWidget(self.note)
        self.error = plain('')
        layout.addWidget(self.error)
        save = QPushButton('保存处理结果')
        save.clicked.connect(self.save)
        layout.addWidget(save)

    def save(self):
        try:
            self.parent().reports.update(self.report, operator=self.operator.text(),
                note=self.note.text(), status=self.status.currentText())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        except (sqlite3.Error, OSError):
            self.error.setText('处理结果保存失败，请重试。')
            return
        self.parent().refresh_board()
        self.accept()
