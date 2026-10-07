"""Customer-view chat simulator using the shared reply and summary services."""
import copy
import sqlite3
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QTextEdit, QScrollArea,
)

from copilot.agent import run_case
from copilot.llm import ModelConfig
from copilot.reply_llm import generate_reply
from copilot.simulation import SimulationProvider
from copilot.store import ReviewStore
from copilot.summary import digest
from desktop.handover import HandoverPane
from desktop.model_settings import configure_model
from desktop.theme import STYLE
from desktop.widgets import ChatFeed
from desktop.window import button, label, panel


class ReplyWorker(QThread):
    ready = Signal(object)

    def __init__(self, result, config, summary, parent):
        super().__init__(parent)
        self.result, self.config, self.summary = result, config, summary

    def run(self):
        try:
            output = generate_reply(self.result, self.config, summary=self.summary)
        except Exception:
            output = {'status': 'error', 'text': ''}
        self.ready.emit(output)


class SimulationHandover(HandoverPane):
    def confirm_model_context(self, context):
        # The explicit summary button in this isolated simulator initiates the call.
        return True

    def notice_text(self):
        if self.raw.get('source') and self.source_changed():
            return '有新消息 · 摘要待更新，请点击“更新摘要”。'
        return super().notice_text()

    def render(self):
        super().render()
        self.consumer_label.hide()
        self.product_label.hide()
        self.update_button.setText('更新摘要' if self.raw.get('source') else '生成摘要')
        # Keep the primary action and freshness state above long summaries.
        actions = self.update_button.parentWidget()
        self.layout.removeWidget(actions)
        self.layout.removeWidget(self.notice)
        self.layout.insertWidget(0, actions)
        self.layout.insertWidget(1, self.notice)


class SimulationWindow(QMainWindow):
    def __init__(self, directory, settings=None, api_key=''):
        super().__init__()
        directory.mkdir(parents=True, exist_ok=True)
        self.store = ReviewStore(directory / 'tests.sqlite3')
        self.provider = SimulationProvider(self.store)
        self.settings, self.api_key = dict(settings or {}), api_key
        # Model settings stay alongside the main settings, not inside test records.
        self.settings_directory = directory.parent
        self.result = None
        self.session = None
        self.worker = self.summary_worker = None
        self.reply_busy = self.summary_busy = False
        self.request = None
        self.pending_output = None
        self.customer_drafts = {}
        self.notices = {}
        self.setWindowTitle('共情副驾 · 模拟对话测试')
        self.resize(1320, 820)
        self.setMinimumSize(1040, 640)
        self.setStyleSheet(STYLE)
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 10)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split)
        self.setCentralWidget(root)

        left, left_layout = panel('surface')
        left.setMinimumWidth(180)
        left.setMaximumWidth(290)
        left_layout.addWidget(label('模拟对话', 'heading'))
        left_layout.addWidget(label('你扮演客户，AI 扮演客服', 'muted'))
        self.new_test_button = button('＋ 新建空白对话', self.new_test, True)
        left_layout.addWidget(self.new_test_button)
        self.sessions = QListWidget()
        self.sessions.setWordWrap(False)
        self.sessions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sessions.currentItemChanged.connect(self.select_session)
        left_layout.addWidget(self.sessions, 1)
        left_layout.addWidget(button('模型连接设置', self.configure_model))
        left_layout.addWidget(label('独立测试记录 · 仅本机保存', 'muted'))
        split.addWidget(left)

        center, center_layout = panel()
        center.setMinimumWidth(420)
        header, head = panel('surface')
        self.title = label('AI 客服', 'heading')
        self.conversation_meta = label('空白对话 · 没有关联订单或工单', 'muted')
        row = QHBoxLayout()
        row.addWidget(self.title, 1)
        self.risk_badge = label('待输入', 'riskBadge')
        row.addWidget(self.risk_badge)
        self.risk_button = button('查看依据', self.show_risk)
        row.addWidget(self.risk_button)
        head.addLayout(row)
        head.addWidget(self.conversation_meta)
        center_layout.addWidget(header)
        self.chat = ChatFeed(customer_view=True)
        center_layout.addWidget(self.chat, 1)
        self.test_notice = label('', 'muted')
        center_layout.addWidget(self.test_notice)
        composer, compose = panel('surface')
        self.customer_input = QTextEdit()
        self.customer_input.setAcceptRichText(False)
        self.customer_input.setPlaceholderText('以客户身份输入，例如：收到的瓶子破了，我想换货。')
        self.customer_input.setMinimumHeight(70)
        self.customer_input.setMaximumHeight(130)
        compose.addWidget(self.customer_input)
        row = QHBoxLayout()
        row.addWidget(label('Ctrl+Enter 发送 · Enter 换行', 'muted'), 1)
        self.retry_button = button('重试回复', self.generate_model)
        row.addWidget(self.retry_button)
        self.customer_send = button('发送', self.send_customer, True)
        row.addWidget(self.customer_send)
        compose.addLayout(row)
        center_layout.addWidget(composer)
        split.addWidget(center)

        right, right_layout = panel('surface')
        right.setMinimumWidth(330)
        right_layout.addWidget(label('会话摘要', 'heading'))
        self.facts = QScrollArea()
        self.facts.setWidgetResizable(True)
        self.facts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.facts.handover = None
        right_layout.addWidget(self.facts)
        split.addWidget(right)
        split.setSizes([210, 680, 380])
        split.setStretchFactor(1, 1)
        QShortcut(QKeySequence('Ctrl+Return'), self.customer_input, activated=self.send_customer)
        self.statusBar().showMessage('发送消息或生成摘要会调用已配置的 AI · 空白测试不提供订单、工单或图片凭证 · 时间为 UTC')
        self.populate_sessions()
        if self.sessions.count():
            self.sessions.setCurrentRow(0)
        else:
            self.new_test()

    def configure_model(self):
        configure_model(self)

    def busy(self):
        return self.reply_busy or self.summary_busy

    def set_notice(self, message):
        self.notices[self.session] = message
        self.test_notice.setText(message)

    def save_input(self):
        if self.session:
            text = self.customer_input.toPlainText()
            self.customer_drafts[self.session] = text
            self.store.save_composer_draft('simulation-customer', self.session, {'edited': text})

    def populate_sessions(self):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        conversations = {sid: self.provider.messages(sid) for sid in self.provider.sessions()}
        ordered = sorted(conversations, key=lambda sid: conversations[sid][-1]['发送时间'] if conversations[sid] else '', reverse=True)
        for sid in ordered:
            messages = conversations[sid]
            draft = self.store.composer_draft('simulation-customer', sid) or {}
            title = (messages[0]['message_text'] if messages else '未发送 · ' + draft.get('edited', '')).replace('\n', ' ')[:24]
            item = QListWidgetItem(title)
            item.setToolTip(title + '\n' + sid)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.sessions.addItem(item)
            if sid == self.session:
                self.sessions.setCurrentItem(item)
        self.sessions.blockSignals(False)

    def new_test(self):
        if self.summary_busy:
            return
        try:
            self.save_input()
        except (OSError, sqlite3.Error):
            self.set_notice('保存输入失败，文字已保留，请重试。')
            return
        self.session = 'TEST-' + uuid4().hex[:12]
        self.populate_sessions()
        self.sessions.setCurrentRow(-1)
        self.customer_input.clear()
        self.refresh_chat()
        self.customer_input.setFocus()

    def select_session(self, item, previous=None):
        if item is None or self.summary_busy:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid == self.session:
            return
        try:
            self.save_input()
            saved = self.store.composer_draft('simulation-customer', sid) or {}
        except (OSError, sqlite3.Error):
            self.set_notice('保存输入失败，仍保留当前对话，请重试。')
            self.populate_sessions()
            return
        self.session = sid
        self.customer_input.setPlainText(self.customer_drafts.get(sid, saved.get('edited', '')))
        self.refresh_chat()

    def refresh_chat(self):
        messages = self.provider.messages(self.session)
        same_chat = bool(self.chat.messages and messages and self.chat.messages[0]['message_id'] == messages[0]['message_id'])
        reading = same_chat and not self.chat._following_end
        scroll = self.chat.verticalScrollBar().value()
        self.chat.set_messages(messages)
        if reading:
            self.chat.stop_following()
            self.chat.verticalScrollBar().setValue(scroll)
        old = self.facts.takeWidget()
        if old:
            old.deleteLater()
        self.facts.handover = None
        self.title.setText('AI 客服')
        self.conversation_meta.setText(f'{len(messages)} 条消息 · 你正在扮演客户')
        self.result = run_case(self.provider, self.session, messages[-1]['发送时间']) if messages else None
        if self.result:
            pane = SimulationHandover(self.provider, self.store.path, self.session, self.facts)
            self.facts.handover = pane
            self.facts.setWidget(pane)
        else:
            blank, content = panel()
            content.addWidget(label('摘要待生成', 'heading'))
            content.addWidget(label('先发送一条客户消息，再点击生成摘要。', 'muted'))
            content.addStretch()
            self.facts.setWidget(blank)
            self.chat.show_empty()
            self.chat.flow.itemAt(0).widget().setText('从一句客户消息开始\nAI 将在这里回复你')
        risk = self.result['risk']['level'] if self.result else '待输入'
        self.risk_badge.setText(risk)
        self.risk_badge.setProperty('level', risk)
        self.risk_badge.style().unpolish(self.risk_badge)
        self.risk_badge.style().polish(self.risk_badge)
        self.risk_button.setEnabled(bool(self.result))
        self.test_notice.setText(self.notices.get(self.session, '发送后 AI 自动回复 · 摘要按需生成'))
        self.update_controls()

    def update_controls(self):
        self.customer_send.setEnabled(not self.busy())
        self.retry_button.setVisible(bool(self.result and self.result['case']['messages'][-1]['角色'] == '买家'))
        self.retry_button.setEnabled(not self.busy())
        self.sessions.setEnabled(not self.summary_busy)
        self.new_test_button.setEnabled(not self.summary_busy)
        if self.facts.handover:
            self.facts.handover.setEnabled(not self.busy())

    def summary_busy_changed(self, busy):
        self.summary_busy = busy
        self.update_controls()

    def current_summary(self):
        pane = self.facts.handover
        if not pane:
            return None
        try:
            return pane.reply_summary()
        except ValueError:
            # Full current messages remain the source when the summary is stale.
            return None

    def send_customer(self):
        if self.busy():
            return
        try:
            self.provider.append_customer(self.session, self.customer_input.toPlainText())
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.set_notice(str(exc) if isinstance(exc, ValueError) else '保存失败，客户文字已保留，请重试。')
            return
        self.customer_input.clear()
        try:
            self.save_input()
        except (OSError, sqlite3.Error):
            self.set_notice('消息已保存，但输入草稿清理失败；请勿重复发送。')
        self.populate_sessions()
        self.refresh_chat()
        self.generate_model()

    def generate_model(self):
        if self.busy() or not self.result or self.result['case']['messages'][-1]['角色'] != '买家':
            return
        config = ModelConfig(self.settings.get('base_url', ''), self.settings.get('model', ''), self.api_key)
        try:
            config.validate()
        except ValueError:
            self.set_notice('请先打开左侧“模型连接设置”，配置后点击重试回复。')
            return
        summary = self.current_summary()
        self.request = (self.session, copy.deepcopy(self.provider.messages(self.session)), digest(summary))
        self.pending_output = None
        self.reply_busy = True
        self.set_notice('AI 正在回复…你可以先输入下一条消息。')
        self.update_controls()
        worker = ReplyWorker(copy.deepcopy(self.result), config, summary, self)
        self.worker = worker
        worker.ready.connect(self.receive_reply)
        worker.finished.connect(self.reply_finished)
        worker.start()

    def receive_reply(self, output):
        self.pending_output = output

    def reply_finished(self):
        # Handle results only after the worker has finished; no UI event can start
        # another request while persistence and the current view are refreshed.
        sid, messages, summary_digest = self.request
        output = self.pending_output or {}
        notice = '回复生成失败或未通过校验，请重试。'
        if sid != self.session:
            self.notices[sid] = '已切换对话，旧回复未写入；点击重试回复。'
        else:
            try:
                if messages != self.provider.messages(sid) or summary_digest != digest(self.current_summary()):
                    notice = '聊天或摘要已变化，未采用旧回复，请重试。'
                    self.refresh_chat()
                elif output.get('status') == 'model':
                    self.provider.append_reply(sid, output['text'], messages)
                    notice = 'AI 已回复 · 可以继续发送消息'
                    self.populate_sessions()
                    self.refresh_chat()
            except (ValueError, KeyError, OSError, sqlite3.Error):
                notice = '回复保存失败或记录已变化，请重试；客户消息已保留。'
            self.set_notice(notice)
        self.reply_busy = False
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.update_controls()

    def show_risk(self):
        if self.facts.handover:
            risk = self.result['risk']
            self.facts.handover.show_text('风险依据', risk['reason'] + '\n\n' + '\n\n'.join(
                e['quote'] + '\n消息 ' + e['message_id'] for e in risk['evidence']))

    def closeEvent(self, event):
        if self.busy():
            self.set_notice('AI 请求仍在进行，请等待完成后关闭。')
            event.ignore()
            return
        try:
            self.save_input()
        except (OSError, sqlite3.Error):
            self.set_notice('输入保存失败，请复制文字后重试关闭。')
            event.ignore()
            return
        event.accept()


def main():
    import sys
    from PySide6.QtWidgets import QApplication
    from desktop.config import user_directory, read_settings, load_model_settings
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    settings, key = load_model_settings(read_settings())
    window = SimulationWindow(user_directory() / 'simulation', settings, key)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
