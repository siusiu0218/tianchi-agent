"""Packaged, offline check for the rejected summary review path."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from copilot.summary_llm import SummaryValidationError
from desktop import handover


def check(window, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for index in range(window.sessions.count()):
        if window.sessions.item(index).data(Qt.ItemDataRole.UserRole) == 'S00053':
            window.sessions.setCurrentRow(index)
            break
    else:
        raise AssertionError('S00053 is missing')
    pane = window.facts.handover
    before = pane.raw.copy()
    prior_generate, prior_exec = handover.generate_summary, QMessageBox.exec
    prior_settings, prior_key = dict(window.settings), window.api_key

    def reject_summary(summary, config):
        raise SummaryValidationError('诉求 / 补差价 含无来源数字 40；请核对该项 refs',
                                     '{"items":[{"field":"诉求","topic":"补差价","text":"等待40元到账","refs":["e0"]}]}',
                                     [{'ref': 'e0', 'content': '{"原文":"等待核实"}'}])

    try:
        window.settings.update(base_url='http://localhost:9000/v1', model='test')
        window.api_key = 'test-key'
        handover.generate_summary = reject_summary
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
        pane.update_button.click()
        worker = window.summary_worker
        assert worker is not None and worker.wait(3000)
        QApplication.processEvents()
        assert pane.raw == before
        assert pane.rejected_button.isVisible()
        assert '40' in pane.notice.text()
        assert '等待40元到账' in handover.rejected_draft_text(pane.rejected_draft)
        shown = []
        original_show_text = pane.show_text
        pane.show_text = lambda title, value: shown.append((title, value))
        pane.rejected_button.click()
        pane.show_text = original_show_text
        assert shown and '等待40元到账' in shown[0][1]
        parent = pane.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            parent.ensureWidgetVisible(pane.rejected_button)
        QApplication.processEvents()
        assert window.grab().save(str(output / 'summary-rejected-S00053.png'))
    finally:
        handover.generate_summary, QMessageBox.exec = prior_generate, prior_exec
        window.settings, window.api_key = prior_settings, prior_key
    (output / 'result.json').write_text(json.dumps({'passed': True, 'session': 'S00053',
                                                    'old_summary_preserved': True,
                                                    'rejected_draft_visible': True,
                                                    'live_model_called': False}), encoding='utf-8')
