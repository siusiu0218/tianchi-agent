"""Handover UI: persisted summaries, evidence, corrections and confirmed links."""
from pathlib import Path
import sqlite3
import re
from html import escape

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QDialogButtonBox, QTextEdit, QLineEdit, QComboBox, QFormLayout, QMessageBox, QMenu, QSizePolicy, QScrollArea, QToolButton,
)

from copilot.summary import FIELDS, LOCAL_SOURCE, build_summary, candidates, digest, order_ids
from copilot.summary_store import SummaryStore
from copilot.checklist import ChecklistStore, suggestions
from desktop.checklist import ChecklistWidget
from copilot.agent import assess
from copilot.llm import ModelConfig
from copilot.summary_llm import generate_summary, model_context, SummaryValidationError
import json


def rejected_draft_text(failure):
    draft = failure.get('draft')
    try:
        parsed = json.loads(draft) if isinstance(draft, str) else None
    except ValueError:
        parsed = None
    readable = json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else (draft or '模型未返回可读取的草稿。')
    refs = set()
    if isinstance(parsed, dict) and isinstance(parsed.get('items'), list):
        for item in parsed['items']:
            if isinstance(item, dict) and isinstance(item.get('refs'), list):
                refs.update(ref for ref in item['refs'] if isinstance(ref, str))
    sources = '\n\n'.join(source['ref'] + '：' + source['content']
                          for source in failure.get('sources', []) if source['ref'] in refs)
    return ('校验原因：' + failure['reason'] + '\n\n'
            '以下是未通过校验的模型原稿，未保存为正式摘要，请勿直接作为业务事实。\n\n'
            '模型草稿：\n' + readable + '\n\n'
            '草稿引用的来源：\n' + (sources or '没有可对应的来源引用。'))


class SummaryWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    rejected = Signal(object)

    def __init__(self, summary, config, parent):
        super().__init__(parent)
        self.summary, self.config = summary, config

    def run(self):
        try:
            self.ready.emit(generate_summary(self.summary, self.config))
        except SummaryValidationError as exc:
            self.rejected.emit({'reason': str(exc), 'draft': exc.draft, 'sources': exc.sources})
        except Exception:
            self.failed.emit('模型未返回合规摘要，旧摘要和人工纠正已保留。请检查模型配置或稍后重试。')


def plain(value, parent=None):
    widget = QLabel(value, parent)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def emphasize(value, urgent=False):
    """Escape source text; highlight whole clauses so negation stays visible."""
    if value == '待生成':
        return value
    chunks = re.split(r'([。；;，,\n])', value)
    result = []
    for chunk in chunks:
        safe = escape(chunk)
        if urgent and re.search('不适|红肿|刺痛|医院|就医|过敏', chunk):
            safe = '<b style="color:#bc4860">' + safe + '</b>'
        else:
            safe = re.sub(r'退款|赔偿|报销|换货|补发|回访|尚未确认|均未见确认|待核实|已接受|已完成',
                          lambda match: '<b>' + match.group() + '</b>', safe)
        result.append(safe)
    return ''.join(result).replace('\n', '<br>')


class CompactOverview(QLabel):
    """Three readable preview lines; full wording is available in the fold."""
    def __init__(self, lines, urgent, parent=None):
        super().__init__(parent)
        self.lines, self.is_urgent = lines, urgent
        self.setObjectName('summaryBody')
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setToolTip('\n'.join(lines))
        self.setAccessibleName('概述：' + ' '.join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        font = self.font()
        font.setBold(True)
        metrics = QFontMetrics(font)
        self.setText('<br>'.join(emphasize(metrics.elidedText(
            line, Qt.TextElideMode.ElideRight, max(20, self.width() - 4)), self.is_urgent)
            for line in self.lines))
        self.setFixedHeight(metrics.lineSpacing() * len(self.lines) + 8)


class CorrectionDialog(QDialog):
    def __init__(self, pane, item):
        super().__init__(pane)
        self.pane, self.item = pane, item
        self.setWindowTitle('纠正 · ' + item['field'] + ' / ' + item['topic'])
        self.resize(640, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(plain('人工纠正会单独保存，不修改原始记录或风险等级。'))
        if item.get('conflict'):
            layout.addWidget(plain('来源已变化，请核对新证据。当前系统版本：' + item['generated']))
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlainText(item['text'])
        layout.addWidget(self.editor)
        form = QFormLayout()
        self.actor, self.reason = QLineEdit(), QLineEdit()
        form.addRow('操作人', self.actor)
        form.addRow('修改／核实说明', self.reason)
        layout.addLayout(form)
        self.error = plain('')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.pane.ledger.correct(self.pane.session, self.item, self.editor.toPlainText(), self.actor.text(), self.reason.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.pane.render()
        self.accept()


FIELD_TITLES = {'诉求': '客户当前诉求', '经过概述': '前期沟通情况',
                '待解决': '待确认内容', '建议': '建议处理方式'}


class HandoverEditDialog(QDialog):
    """One review action for all four displayed fields, retaining item evidence."""

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setWindowTitle('修改接手要点')
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(plain('按原文逐项核对后修改。待确认内容请在清单中逐项修改。原始记录与风险等级不会改变。'))
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget(scroll)
        fields = QVBoxLayout(container)
        self.editors = []
        for field in ('诉求', '经过概述', '建议'):
            fields.addWidget(plain(FIELD_TITLES[field]))
            for item in pane.displayed['items']:
                if item['field'] != field:
                    continue
                if item.get('conflict'):
                    fields.addWidget(plain('这项来源已变化，请对照新证据复核。'))
                fields.addWidget(plain(item['topic']))
                editor = QTextEdit(container)
                editor.setAcceptRichText(False)
                editor.setPlainText(item['text'])
                editor.setMinimumHeight(72)
                fields.addWidget(editor)
                self.editors.append((item, editor))
        scroll.setWidget(container)
        layout.addWidget(scroll)
        form = QFormLayout()
        self.actor, self.reason = QLineEdit(), QLineEdit()
        form.addRow('操作人', self.actor)
        form.addRow('修改／核实说明', self.reason)
        layout.addLayout(form)
        self.error = plain('')
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def save(self):
        changes = [(item, editor.toPlainText()) for item, editor in self.editors
                   if editor.toPlainText().strip() != item['text']]
        if not changes:
            self.accept()
            return
        try:
            self.pane.ledger.correct_many(self.pane.session, changes, self.actor.text(), self.reason.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.pane.render()
        self.accept()


class LinkDialog(QDialog):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setWindowTitle('可能相关的历史会话')
        self.resize(620, 430)
        layout = QVBoxLayout(self)
        layout.addWidget(plain('仅展示有相同订单标识的候选。相同订单不等于相同问题，请核对原文后按问题确认。'))
        self.rows = candidates(pane.provider, pane.session)
        known = {r['session'] for r in self.rows}
        for other, selected in pane.ledger.links(pane.session).items():
            if other not in known:
                self.rows.append({'session': other, 'orders': [], 'topics': selected})
        self.choice, self.topic = QComboBox(), QComboBox()
        for row in self.rows:
            self.choice.addItem(row['session'] + (' · 相同订单 ' + '、'.join(row['orders']) if row['orders'] else ' · 原关联依据失效，仅可解除'), row)
        layout.addWidget(self.choice)
        layout.addWidget(self.topic)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.actor = QLineEdit()
        self.actor.setPlaceholderText('填写操作人')
        layout.addWidget(self.actor)
        self.error = plain('')
        layout.addWidget(self.error)
        self.confirm = QPushButton('确认属于同一问题并纳入')
        self.remove = QPushButton('解除所选问题的关联')
        self.confirm.clicked.connect(lambda: self.commit(True))
        self.remove.clicked.connect(lambda: self.commit(False))
        layout.addWidget(self.confirm)
        layout.addWidget(self.remove)
        self.choice.currentIndexChanged.connect(self.show_candidate)
        self.show_candidate()

    def show_candidate(self):
        row = self.choice.currentData()
        self.topic.clear()
        if not row:
            self.preview.setPlainText('当前资料没有可确认的同订单跨会话候选；没有跨会话结果不代表消费者没有再次联系。')
            self.confirm.setEnabled(False)
            self.remove.setEnabled(False)
            return
        current_topics = self.pane.pending['topics']
        available = set(row['topics']) & set(current_topics)
        available.update(self.pane.ledger.links(self.pane.session).get(row['session'], []))
        self.topic.addItems(sorted(available))
        self.confirm.setEnabled(bool(available) and bool(row['orders']))
        self.remove.setEnabled(bool(available))
        self.preview.setPlainText('\n\n'.join(m['发送时间'] + ' ' + m['角色'] + '\n' + m['message_text'] for m in self.pane.provider.messages(row['session'])))

    def commit(self, active):
        row = self.choice.currentData()
        if not row or not self.topic.currentText():
            return
        if active and not row['orders']:
            self.error.setText('关联依据失效，不能重新确认。')
            return
        try:
            self.pane.ledger.set_link(self.pane.session, row['session'], self.topic.currentText(), active, self.actor.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        # Explicit confirmation is also explicit authorization to refresh the summary.
        self.pane.refresh_pending()
        self.pane.update_summary()
        self.accept()


class HandoverPane(QWidget):
    def __init__(self, provider, state_path, session, parent=None):
        super().__init__(parent)
        self.provider, self.session = provider, session
        namespace = digest(str(Path(provider.source).resolve()).casefold())
        self.ledger = SummaryStore(state_path, namespace)
        self.checklist = ChecklistStore(state_path, namespace)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)
        self.pending = self.generate()
        saved = self.ledger.latest(session)
        # Earlier versions saved a local draft merely by opening a session.
        # That draft is not evidence that a person chose to generate a summary.
        legacy_auto = (saved and saved.get('source') == LOCAL_SOURCE
                       and not saved.get('explicit') and not self.ledger.history(session))
        self.raw = saved if saved and not legacy_auto else {
            **self.pending, 'items': [], 'source': '', 'topics': []}
        self.changed = set()
        self.rejected_draft = None
        self.render()

    def generate(self):
        links = self.ledger.links(self.session)
        valid = {}
        for other, selected in links.items():
            if other in self.provider.sessions() and order_ids(self.provider, other) & order_ids(self.provider, self.session):
                valid[other] = selected
        cases, snapshots = [], {}
        for session in [self.session, *valid]:
            messages = self.provider.messages(session)
            cases.append(self.provider.get_case(session, messages[-1]['发送时间']))
            if session == self.session:
                snapshots[session] = self.provider.ticket_snapshot(session)
        summary = build_summary(cases, snapshots, valid)
        summary['inactive_links'] = sorted(set(links) - set(valid))
        summary['risk'] = assess(cases[0])
        return summary

    def refresh_pending(self):
        try:
            self.pending = self.generate()
            if self.raw.get('source') == LOCAL_SOURCE and self.source_changed():
                self.pending['source'] = LOCAL_SOURCE
                self.model_ready(self.pending)
                return
            self.urgent.setText(self.risk_text())
            self.urgent.setToolTip('\n'.join(e['quote'] + '\n消息 ' + e['message_id'] for e in self.pending['risk']['evidence']))
            self.urgent.setObjectName('summaryRisk' if self.pending['risk']['level'] == 'P0' else 'muted')
            self.urgent.style().unpolish(self.urgent)
            self.urgent.style().polish(self.urgent)
            self.notice.setText(self.notice_text())
            self.update_button.setText('生成摘要' if not self.raw.get('source') else
                                       ('AI 更新摘要' if self.source_changed() else 'AI 精炼摘要'))
        except (OSError, ValueError, KeyError, sqlite3.Error):
            self.notice.setText('读取新信息失败，保留旧摘要，请重新载入资料后重试。')

    def notice_text(self):
        if not self.raw.get('source'):
            return '摘要尚未生成 · 点击“生成摘要”后显示接手要点'
        if self.source_changed():
            return '有新记录 · 摘要待更新；可在“查看详情”中选择本地重新整理'
        return self.raw.get('source', '尚未生成 · 点击下方生成摘要')

    def source_changed(self):
        """Compare source facts, ignoring a digest change caused only by code version."""
        if not self.raw.get('source'):
            return False
        return any(self.pending.get(key) != self.raw.get(key)
                   for key in ('evidence', 'coverage', 'inactive_links'))

    def risk_text(self):
        risk = self.pending['risk']
        if risk['level'] == 'P0':
            return 'P0 · 不适或就医报告，优先核实'
        return risk['level'] + ' · 风险依据见详情'

    def update_summary(self):
        self.generate_model()

    def reply_summary(self):
        current = self.generate()
        self.pending = current
        if not self.raw.get('source'):
            return None
        if self.source_changed():
            raise ValueError('资料已变化，请在“查看详情”中选择“按最新记录重新整理（本地）”，核对后再生成回复。')
        summary = self.ledger.apply(self.session, self.raw)
        summary['risk'] = current['risk']
        if any(i.get('conflict') for i in summary['items']):
            raise ValueError('摘要中有人工纠正需要复核，请先核对后再生成回复。')
        summary['checklist'] = [{'text': item['text'], 'done': bool(item['done']), 'refs': item['refs']}
                                for item in self.checklist.items(self.session)]
        return summary

    def fold(self, title, value):
        button = QPushButton('▸ ' + title, self)
        button.setCheckable(True)
        detail = QTextEdit(self)
        detail.setReadOnly(True)
        detail.setPlainText(value)
        detail.setMinimumHeight(180)
        detail.hide()
        button.toggled.connect(detail.setVisible)
        button.toggled.connect(lambda yes: button.setText(('▾ ' if yes else '▸ ') + title))
        self.layout.addWidget(button)
        self.layout.addWidget(detail)

    def render(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        messages = self.provider.messages(self.session)
        case = self.provider.get_case(self.session, messages[-1]['发送时间'])
        # The workbook has no consumer name field. Do not invent a nickname.
        self.consumer_label = plain('消费者：未提供姓名（会话 ' + self.session + '）')
        self.layout.addWidget(self.consumer_label)
        products = list(dict.fromkeys(o.get('商品名称', '') for o in case['orders'] if o.get('商品名称')))
        names = [re.sub(r'^【[^】]*】\s*', '', name) for name in products]
        self.product_label = plain('商品：' + ('、'.join(names) if names else '暂无关联商品'))
        self.product_label.setToolTip('、'.join(products))
        self.layout.addWidget(self.product_label)
        self.urgent = plain(self.risk_text())
        self.urgent.setObjectName('summaryRisk' if self.pending['risk']['level'] == 'P0' else 'muted')
        self.urgent.setToolTip('\n'.join(e['quote'] + '\n消息 ' + e['message_id'] for e in self.pending['risk']['evidence']))
        self.layout.addWidget(self.urgent)
        self.notice = plain(self.notice_text())
        self.notice.setObjectName('muted')
        self.notice.setToolTip('；'.join(k + ' ' + v for k, v in self.pending['coverage'].items()))
        self.update_button = QPushButton('生成摘要' if not self.raw.get('source') else
                                         ('AI 更新摘要' if self.source_changed() else 'AI 精炼摘要'))
        self.update_button.setObjectName('summaryAction')
        self.update_button.clicked.connect(self.update_summary)
        data = self.ledger.apply(self.session, self.raw)
        self.displayed = data
        # The model summary is prose for review; checklist proposals come from
        # the deterministic source pass so a rephrased model item does not
        # duplicate an existing follow-up action.
        self.checklist.sync(self.session, suggestions(self.pending) if self.raw.get('source') else [],
                            retire_stale=True)
        available = [i for i in data['items'] if self.raw.get('source') or i.get('correction')]
        issue = '、'.join(self.pending.get('topics', [])) if available else '待生成'
        self.problem_label = plain('问题：' + (issue or '待核实'))
        self.problem_label.setStyleSheet('font-weight:600;')
        self.layout.addWidget(self.problem_label)
        self.full_toggle = QPushButton('▾ 接手要点', self)
        self.full_toggle.setObjectName('fold')
        self.full_toggle.setCheckable(True)
        self.full_summary = QWidget(self)
        full_layout = QVBoxLayout(self.full_summary)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_layout.setSpacing(8)
        self.full_toggle.toggled.connect(self.full_summary.setVisible)
        self.full_toggle.toggled.connect(lambda yes: self.full_toggle.setText(('▾ ' if yes else '▸ ') + '接手要点'))
        self.layout.addWidget(self.full_toggle)
        self.layout.addWidget(self.full_summary)
        self.full_toggle.setChecked(True)
        self.field_labels = {}
        for field in ('诉求', '经过概述', '建议', '待解决'):
            heading = plain(FIELD_TITLES[field] + '：')
            heading.setObjectName('summaryHeading')
            field_header = QHBoxLayout()
            field_header.addWidget(heading)
            evidence_button = QToolButton(self.full_summary)
            evidence_button.setObjectName('evidenceButton')
            evidence_button.setIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'file-search.svg')))
            evidence_button.setIconSize(QSize(17, 17))
            evidence_button.setFixedSize(28, 28)
            evidence_button.setToolTip('查看依据')
            evidence_button.setAccessibleName(FIELD_TITLES[field] + ' · 查看依据')
            evidence_button.setCursor(Qt.CursorShape.PointingHandCursor)
            evidence_button.clicked.connect(lambda checked=False, f=field: self.show_field(f))
            evidence_button.setEnabled(bool(self.raw.get('source')))
            field_header.addWidget(evidence_button)
            field_header.addStretch()
            full_layout.addLayout(field_header)
            rows = [x for x in data['items'] if x['field'] == field and (self.raw.get('source') or x.get('correction'))]
            lines = []
            for item in rows:
                prefix = ('〔已更新〕' if item['id'] in self.changed else '')
                prefix += ('〔已纠正〕' if item.get('correction') else '')
                if item.get('conflict'):
                    prefix += '〔纠正需复核〕'
                lines.append(prefix + item['text'])
            body = plain('\n'.join(dict.fromkeys(lines)) or
                         ('待生成' if not self.raw.get('source') else '现有记录未显示该项内容，请人工核对。'))
            body.setObjectName('summaryBody')
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setText(emphasize(body.text(), self.pending['risk']['level'] == 'P0'))
            self.field_labels[field] = body
            if field == '待解决':
                # Keep the source summary available through "查看依据"; the live
                # handover surface is the human-controlled checklist.
                self.checklist_widget = None
                if self.raw.get('source') or self.checklist.items(self.session):
                    self.checklist_widget = ChecklistWidget(self.checklist, self.session,
                                                           data['evidence'], self.full_summary)
                    full_layout.addWidget(self.checklist_widget)
                else:
                    full_layout.addWidget(plain('待生成'))
            else:
                full_layout.addWidget(body)
        if data['orphaned_edits']:
            self.layout.addWidget(plain('有人工纠正待匹配 · 请在详情中核对'))
        if self.raw.get('inactive_links'):
            self.layout.addWidget(plain('部分关联的订单依据已失效，未纳入：' + '、'.join(self.raw['inactive_links'])))
        self.layout.addWidget(self.notice)
        self.rejected_button = QPushButton('查看未通过的 AI 草稿与原因', self)
        self.rejected_button.clicked.connect(self.show_rejected_draft)
        self.rejected_button.setVisible(self.rejected_draft is not None)
        self.layout.addWidget(self.rejected_button)
        actions = QWidget(self)
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 4, 0, 0)
        self.correct_button = QPushButton('修改接手要点', actions)
        self.correct_button.setObjectName('summaryAction')
        self.correct_button.clicked.connect(lambda: HandoverEditDialog(self).exec())
        self.correct_button.setEnabled(bool(self.raw.get('source')))
        row.addWidget(self.correct_button)
        row.addWidget(self.update_button)
        details = QPushButton('查看详情', actions)
        details.setObjectName('summaryAction')
        menu = QMenu(details)
        for field in FIELDS:
            action = menu.addAction(FIELD_TITLES[field] + ' · 查看依据', lambda f=field: self.show_field(f))
            action.setEnabled(bool(self.raw.get('source')))
        menu.addSeparator()
        menu.addAction('按最新记录重新整理（本地）', self.update_local)
        menu.addAction('风险依据', lambda: self.show_text('风险依据', '\n\n'.join(e['quote'] + '\n消息 ' + e['message_id'] for e in self.pending['risk']['evidence']) or '暂无触发证据'))
        menu.addAction('原文时间线', lambda: self.show_text('原文时间线', '\n\n'.join(x['时间'] + ' · ' + x['会话'] + ' · ' + x['角色'] + '\n' + x['原文'] + '\n' + x['ref'] for x in data['timeline'])))
        menu.addAction('人工修改记录', lambda: self.show_text('人工修改记录', '\n\n'.join(x['created'] + ' · ' + x['actor'] + '\n' + x['item'] + '\n原内容：' + x['original'] + '\n修改：' + x['edited'] + '\n说明：' + x['reason'] for x in self.ledger.history(self.session)) or '暂无人工修改'))
        menu.addAction('本次移除的事项', lambda: self.show_text('本次移除的事项', '\n'.join(sorted(getattr(self, 'removed', []))) or '无'))
        menu.addAction('可能相关的历史会话', lambda: LinkDialog(self).exec())
        details.setMenu(menu)
        row.addWidget(details)
        row.addStretch()
        self.layout.addWidget(actions)

    def update_local(self):
        current = self.generate()
        current['source'] = LOCAL_SOURCE
        current['explicit'] = True
        self.model_ready(current)

    def show_text(self, title, value):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(640, 500)
        layout = QVBoxLayout(dialog)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(value)
        layout.addWidget(viewer)
        dialog.exec()

    def show_rejected_draft(self):
        if self.rejected_draft:
            self.show_text('未通过的 AI 草稿 · 仅供核对', rejected_draft_text(self.rejected_draft))

    def model_rejected(self, failure):
        self.rejected_draft = failure
        self.notice.setText('AI 摘要未通过校验，旧摘要和人工纠正已保留。原因：' + failure['reason'])
        self.rejected_button.show()

    def show_evidence(self, item):
        dialog = QDialog(self)
        dialog.setWindowTitle('来源依据 · ' + item['topic'])
        dialog.resize(640, 520)
        layout = QVBoxLayout(dialog)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText('\n\n'.join(r + '\n' + '\n'.join(f'{k}：{v}' for k, v in self.raw['evidence'][r].items()) for r in item['refs']))
        layout.addWidget(viewer)
        dialog.exec()

    def show_field(self, field):
        dialog = QDialog(self)
        dialog.setWindowTitle(FIELD_TITLES[field] + ' · 完整内容与依据')
        dialog.resize(700, 570)
        layout = QVBoxLayout(dialog)
        selector = QComboBox()
        for item in self.displayed['items']:
            if item['field'] == field:
                selector.addItem(item['topic'], item)
        layout.addWidget(selector)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        layout.addWidget(viewer)
        def show():
            item = selector.currentData()
            if not item:
                return
            extra = '\n当前系统表述：' + item['generated'] if item.get('conflict') else ''
            viewer.setPlainText(item['text'] + extra + '\n\n来源依据：\n\n' + '\n\n'.join(r + '\n' + '\n'.join(f'{k}：{v}' for k, v in self.raw['evidence'][r].items()) for r in item['refs']))
        selector.currentIndexChanged.connect(show)
        show()
        dialog.exec()

    def generate_model(self):
        root = self.window()
        if getattr(root, 'worker', None) and root.worker.isRunning():
            self.notice.setText('回复模型仍在运行，请等待完成后再概括摘要。')
            return
        settings = getattr(root, 'settings', {})
        config = ModelConfig(settings.get('base_url', ''), settings.get('model', ''), getattr(root, 'api_key', ''))
        try:
            config.validate()
            pending = self.generate()
            previous = self.ledger.apply(self.session, self.raw)
            pending['previous_items'] = [{'field': i['field'], 'topic': i['topic'], 'text': i['text'],
                                          'human_corrected': bool(i.get('correction'))} for i in previous['items']
                                         if self.raw.get('source') or i.get('correction')]
            pending['previous_items'].extend({'field': e['item'].split(':', 1)[0], 'topic': e['item'].split(':', 1)[-1],
                                              'text': e['edited'], 'human_corrected': True, 'unmatched': True}
                                             for e in previous['orphaned_edits'])
            context, _ = model_context(pending)
        except ValueError as exc:
            QMessageBox.information(self, '请先检查模型设置', str(exc))
            return
        if getattr(root, 'summary_worker', None) and root.summary_worker.isRunning():
            return
        confirm = QMessageBox(self)
        confirm.setWindowTitle('确认生成服务摘要')
        confirm.setText('将向配置的模型接口发送所列聊天与必要业务字段，用于概括服务摘要。长数字和邮箱已隐藏，文本可能仍含个人信息；请展开查看实际发送内容。')
        confirm.setDetailedText(json.dumps(context, ensure_ascii=False, indent=2))
        confirm.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Ok:
            return
        self.rejected_draft = None
        self.rejected_button.hide()
        self.notice.setText('正在概括服务经过、诉求和待办…旧摘要保持可见。')
        self.setEnabled(False)
        for name in ('sessions', 'open_button', 'model_button'):
            widget = getattr(root, name, None)
            if widget:
                widget.setEnabled(False)
        worker = SummaryWorker(pending, config, root)
        root.summary_worker = worker
        worker.ready.connect(self.model_ready)
        worker.failed.connect(self.notice.setText)
        worker.rejected.connect(self.model_rejected)
        def finish():
            if root.summary_worker is worker:
                root.summary_worker = None
            self.setEnabled(True)
            for name in ('sessions', 'open_button', 'model_button'):
                widget = getattr(root, name, None)
                if widget:
                    widget.setEnabled(True)
            worker.deleteLater()
        worker.finished.connect(finish)
        worker.start()

    def model_ready(self, result):
        try:
            self.pending = self.generate()
            if result['fingerprint'] != self.pending['fingerprint']:
                self.notice.setText('生成期间资料已变化，未采用旧结果，请重新生成。')
                return
            previous = {i['id']: i['text'] for i in self.raw['items']}
            self.changed = {i['id'] for i in result['items'] if previous.get(i['id']) != i['text']}
            self.removed = set(previous) - {i['id'] for i in result['items']}
            self.ledger.save(self.session, result)
            self.raw = result
            self.rejected_draft = None
            self.render()
        except (ValueError, KeyError, OSError, sqlite3.Error):
            self.notice.setText('保存摘要失败，旧版本和人工纠正已保留。')
