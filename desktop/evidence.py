"""Readable source messages with literal timestamps and reference identifiers."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from desktop.typography import BodyText
from desktop.widgets import MessageRow, clear_layout, text


class EvidenceMessageRow(MessageRow):
    def fit_width(self, available):
        super().fit_width(available)
        # Use the actual text viewport, including frame pixels at each zoom.
        content = self.bubble.layout()
        margins = content.contentsMargins()
        body_width = max(1, self.bubble.width() - margins.left() - margins.right() - 2)
        body_height = self.body.heightForWidth(body_width)
        self.body.setFixedHeight(body_height)
        height = body_height + margins.top() + margins.bottom() + 2
        if self.image_notice:
            height += self.image_notice.sizeHint().height() + content.spacing()
        self.setFixedHeight(height)
        self.bubble.layout().activate()


class EvidenceView(QScrollArea):
    def __init__(self, parent=None, zoom_factor=1):
        super().__init__(parent)
        self.zoom_factor = zoom_factor
        self.rows = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.flow = QVBoxLayout(self.canvas)
        self.flow.setContentsMargins(16, 14, 16, 18)
        self.flow.setSpacing(14)
        self.flow.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.canvas)

    def set_item(self, item, evidence):
        clear_layout(self.flow)
        self.rows = []
        self.flow.addWidget(text(item['text'], 'summaryBody', selectable=True))
        if item.get('conflict'):
            self.flow.addWidget(text('当前系统表述：' + item['generated'], 'muted', selectable=True))
        self.flow.addWidget(text('来源依据', 'heading'))
        if not item['refs']:
            self.flow.addWidget(text('暂无关联来源，请人工核对。', 'muted'))
        for ref in item['refs']:
            source = evidence.get(ref)
            if source is None:
                self.flow.addWidget(text('来源暂不可用：' + ref, 'muted', selectable=True))
                continue
            if '原文' in source and '角色' in source:
                message = {'message_id': ref, 'message_text': source['原文'],
                           '角色': source['角色'], '发送时间': source.get('时间', ''),
                           '内容类型': source.get('内容类型', ''), 'image_path': source.get('image_path', '')}
                row = EvidenceMessageRow(message)
                row.meta.setText(source['角色'] + '  ·  发送时间 ' + (source.get('时间') or '未提供'))
                row.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                # Keep the full timestamp readable without widening short bubbles.
                caption = text(row.meta.text(), 'messageMeta', selectable=True)
                caption.setAlignment(Qt.AlignmentFlag.AlignRight if row.outgoing else Qt.AlignmentFlag.AlignLeft)
                self.flow.addWidget(caption)
                row.meta.hide()
                row.set_zoom(self.zoom_factor)
                self.rows.append(row)
                self.flow.addWidget(row)
                reference = text('来源 ' + ref, 'muted', selectable=True)
                reference.setAlignment(Qt.AlignmentFlag.AlignRight if row.outgoing else Qt.AlignmentFlag.AlignLeft)
                self.flow.addWidget(reference)
            else:
                card = QFrame()
                card.setObjectName('surface')
                content = QVBoxLayout(card)
                content.addWidget(text('业务记录 · ' + ref, 'muted', selectable=True))
                body = BodyText('\n'.join(f'{key}：{value}' for key, value in source.items()))
                body.setObjectName('summaryBody')
                content.addWidget(body)
                self.flow.addWidget(card)
        self.reflow()
        self.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self.reflow)

    def reflow(self):
        for row in self.rows:
            row.fit_width(self.viewport().width() - 32)
        self.flow.activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()
