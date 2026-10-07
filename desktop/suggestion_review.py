"""Review existing internal checklist items against the current chat snapshot."""
from copy import deepcopy
import getpass

from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QVBoxLayout, QFrame, QSplitter, QWidget, QToolButton)
from PySide6.QtCore import Qt, QTimer
from desktop.widgets import ChatFeed

from copilot.question_conflict_prototype import existing_answer
from copilot.task_guard_prototype import QUESTIONS


class SuggestionReviewDialog(QDialog):
    def __init__(self, parent, store, session, evidence, messages):
        super().__init__(parent)
        self.store, self.session, self.messages = store, session, messages
        self.evidence = deepcopy(evidence)
        self.source = deepcopy(messages())
        self.rows = deepcopy(store.items(session))
        self.setWindowTitle('逐条审核建议 · ' + session)
        self.resize(1060, 700)
        self.setMinimumSize(800, 560)
        self.setObjectName('suggestionReview')
        self.setStyleSheet("""
            QDialog#suggestionReview { background:#f5f6f7; }
            QDialog#suggestionReview QLabel { color:#263238; font-size:13px; }
            QDialog#suggestionReview QLabel#reviewTitle { font-size:20px; font-weight:600; }
            QDialog#suggestionReview QLabel#reviewMuted { color:#78858d; font-size:12px; }
            QDialog#suggestionReview QFrame#reviewCard { background:white; border:1px solid #e4e8eb; border-radius:10px; }
            QDialog#suggestionReview QTextEdit { background:#fafbfc; border:1px solid #e1e6e9; border-radius:7px; padding:10px; font-size:14px; color:#24323a; }
            QDialog#suggestionReview QComboBox { background:white; border:1px solid #e1e6e9; border-radius:7px; padding:9px; font-size:13px; }
            QDialog#suggestionReview QPushButton { background:white; border:1px solid #dce3e6; border-radius:6px; padding:9px 14px; font-size:13px; }
            QDialog#suggestionReview QPushButton#reviewSave { background:#16865d; color:white; border:0; }
            QDialog#suggestionReview QPushButton#reviewDelete { color:#ae534b; }
            QDialog#suggestionReview QScrollArea { border:0; background:#ededed; }
            QDialog#suggestionReview QWidget#reviewChatCanvas { background:#ededed; }
            QDialog#suggestionReview QFrame#bubbleIn { background:white; border:0; border-radius:7px; }
            QDialog#suggestionReview QFrame#bubbleOut { background:#b6ec8d; border:0; border-radius:7px; }
            QDialog#suggestionReview QLabel#message { color:#222; font-size:14px; }
            QDialog#suggestionReview QLabel#messageMeta { color:#64776c; font-size:10px; }
            QDialog#suggestionReview QLabel#avatar { background:#d7e1eb; color:#50718c; border-radius:6px; font-size:12px; }
            QDialog#suggestionReview QLabel#agentAvatar { background:#d3e6d2; color:#46864b; border-radius:6px; font-size:12px; }
            QDialog#suggestionReview QLabel#date { color:#999; font-size:11px; background:transparent; }
            QDialog#suggestionReview QToolButton { border:0; background:transparent; color:#52776b; padding:4px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel('核对原话，审核待办')
        title.setObjectName('reviewTitle')
        header.addWidget(title)
        header.addStretch()
        subtitle = QLabel(session + '  ·  内部审核')
        subtitle.setObjectName('reviewMuted')
        header.addWidget(subtitle)
        layout.addLayout(header)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QFrame()
        left.setObjectName('reviewCard')
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 12, 0, 0)
        caption = QLabel('   聊天记录    ·    标记“引用依据”的消息与当前待办有关')
        caption.setObjectName('reviewMuted')
        left_layout.addWidget(caption)
        self.chat = ChatFeed()
        self.chat.canvas.setObjectName('reviewChatCanvas')
        self.chat.setAccessibleName('客户与客服聊天记录')
        left_layout.addWidget(self.chat)
        split.addWidget(left)
        right = QFrame()
        right.setObjectName('reviewCard')
        right.setMinimumWidth(290)
        side = QVBoxLayout(right)
        side.setContentsMargins(18, 18, 18, 18)
        side.setSpacing(12)
        side.addWidget(QLabel('当前待办'))
        self.selector = QComboBox()
        self.selector.setMinimumContentsLength(12)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for row in self.rows:
            self.selector.addItem(row['text'], row['id'])
        side.addWidget(self.selector)
        self.editor = QTextEdit()
        self.editor.setAccessibleName('可修改的内部待办')
        self.editor.setMinimumHeight(100)
        self.editor.setMaximumHeight(165)
        side.addWidget(self.editor)
        self.conflict = QLabel()
        self.conflict.setTextFormat(Qt.TextFormat.PlainText)
        self.conflict.setWordWrap(True)
        self.conflict.setObjectName('reviewMuted')
        side.addWidget(self.conflict)
        self.reason = QTextEdit()
        self.reason.setAccessibleName('仍需内部核实的理由')
        self.reason.setPlaceholderText('已有回答但仍需内部核实？请说明原因。')
        self.reason.setMaximumHeight(75)
        side.addWidget(self.reason)
        self.evidence_toggle = QToolButton()
        self.evidence_toggle.setText('查看完整引用信息')
        self.evidence_toggle.setCheckable(True)
        side.addWidget(self.evidence_toggle)
        self.sources = QTextEdit()
        self.sources.setReadOnly(True)
        self.sources.setAccessibleName('完整引用信息')
        self.sources.setMaximumHeight(140)
        self.sources.hide()
        self.evidence_toggle.toggled.connect(self.sources.setVisible)
        side.addWidget(self.sources)
        side.addStretch()
        self.keep = QPushButton('保留 / 保存修改')
        self.keep.setObjectName('reviewSave')
        self.drop = QPushButton('删除此待办')
        self.drop.setObjectName('reviewDelete')
        side.addWidget(self.keep)
        side.addWidget(self.drop)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('reviewMuted')
        side.addWidget(self.status)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([620, 370])
        layout.addWidget(split, 1)
        footer = QHBoxLayout()
        notice = QLabel('仅修改内部待办 · 不发送消息 · 不代表事项办结')
        notice.setObjectName('reviewMuted')
        footer.addWidget(notice)
        footer.addStretch()
        self.close_button = QPushButton('关闭')
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.keep.clicked.connect(lambda: self.apply(False))
        self.drop.clicked.connect(lambda: self.apply(True))
        self.close_button.clicked.connect(self.reject)
        self.selector.currentIndexChanged.connect(self.show_item)
        self.editor.textChanged.connect(self.changed)
        self.show_item()

    def changed(self):
        if self.rows:
            self.status.setText('修改尚未保存；切换事项或关闭将放弃当前未保存编辑。')

    def show_item(self):
        index = self.selector.currentIndex()
        if index < 0:
            self.keep.setEnabled(False)
            self.drop.setEnabled(False)
            self.editor.clear()
            self.status.setText('本会话暂无待审核事项。')
            return
        row = self.rows[index]
        self.editor.setPlainText(row['text'])
        self.reason.clear()
        context = {'messages': [{'ref': m['message_id'], 'role': m['角色'],
                                 'text': m['message_text']} for m in self.source]}
        # Restrict recognition to the exact, previously tested reminder templates.
        kind = next((k for k in ('onset', 'current_change') if row['text'] == QUESTIONS[k]), None)
        self.answers = existing_answer(kind, context) or []
        evidence_parts = []
        for ref in row['refs']:
            detail = self.evidence.get(ref)
            if isinstance(detail, dict):
                body = '\n'.join(str(key) + '：' + str(value) for key, value in detail.items())
            else:
                body = '当前快照未找到此引用'
            evidence_parts.append(ref + '\n' + body)
        evidence_text = '\n\n'.join(evidence_parts)
        chat = '\n\n'.join(m['message_id'] + ' · ' + m['角色'] + '\n' + m['message_text'] for m in self.source)
        self.sources.setPlainText('建议引用依据\n' + (evidence_text or '未关联引用，请人工核对。') + '\n\n当前会话原话\n' + chat)
        display = [dict(m, 发送时间=m.get('发送时间', '')) for m in self.source]
        self.chat.set_messages(display)
        cited = []
        for message_row in self.chat.rows:
            mid = str(message_row.message['message_id'])
            if any(ref == mid or ref == self.session + '/' + mid for ref in row['refs']):
                message_row.meta.setText(message_row.meta.text() + '  ·  引用依据')
                message_row.bubble.setToolTip('当前待办引用：' + mid)
                cited.append(mid)
        if cited:
            QTimer.singleShot(60, lambda mid=cited[0]: self.chat.jump_to_message(mid))
        else:
            QTimer.singleShot(60, lambda: self.chat.verticalScrollBar().setValue(0))

        self.conflict.setText(('已有回答：\n' + '\n'.join(e['ref'] + '：' + e['quote'] for e in self.answers))
                              if self.answers else '请对照左侧原话核实。未识别出重复补问，不代表信息缺失。')
        self.reason.setVisible(bool(self.answers))
        self.keep.setText('仍需内部核实 / 保存' if self.answers else '保留 / 保存修改')
        self.drop.setText('已有回答，不再补问' if self.answers else '删除此待办')
        self.keep.setEnabled(True)
        self.drop.setEnabled(True)
        self.status.setText('待审核；保留不会勾选完成。')

    def apply(self, delete):
        index = self.selector.currentIndex()
        if index < 0:
            return
        row = self.rows[index]
        current = next((r for r in self.store.items(self.session) if r['id'] == row['id']), None)
        if self.messages() != self.source or current != row:
            self.status.setText('来源或待办已变化，请关闭并重新打开审核；本次未保存。')
            return
        text = self.editor.toPlainText().strip()
        if not delete and (not text or (self.answers and not self.reason.toPlainText().strip())):
            self.status.setText('请填写事项；已有回答仍需保留时，请说明内部核实理由。')
            return
        try:
            if delete:
                self.store.delete(row['id'], getpass.getuser())
                self.keep.setEnabled(False)
                self.drop.setEnabled(False)
                self.status.setText('已确认不再补问，待办已删除。' if self.answers else '待办已删除，操作记录保留。')
            else:
                if self.answers:
                    text += '\n内部核实理由：' + self.reason.toPlainText().strip()
                if text != row['text']:
                    self.store.edit(row['id'], text, getpass.getuser(), row['refs'])
                self.rows[index] = next(r for r in self.store.items(self.session) if r['id'] == row['id'])
                self.selector.setItemText(index, text)
                self.status.setText('已保留内部待办；未发送消息，也未勾选完成。')
        except ValueError as exc:
            self.status.setText(str(exc))
