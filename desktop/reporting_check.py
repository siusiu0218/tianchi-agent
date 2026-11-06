"""Packaged UI acceptance run using an isolated temporary database only."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QMessageBox
from desktop.reporting import ReportDialog, HandleReportDialog, AllChatsDialog
from copilot.reports import ReportStore
from copilot.reply_llm import reply_context
from copilot.summary import FIELDS
from desktop import handover
from desktop.checklist import ReadOnlyChecklist
from PIL import Image


def check(window, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def capture(widget, name):
        widget.show()
        QApplication.processEvents()
        if not widget.grab().save(str(output / name)):
            raise RuntimeError('Unable to save screenshot')

    window.draft.setPlainText('本地验收回复')
    window.reply_button.click()
    assert not window.reports.reports()
    capture(window, 'inbox.png')
    handover_checks = []
    for session in ('S00268', 'S00001'):
        for index in range(window.sessions.count()):
            if window.sessions.item(index).data(Qt.ItemDataRole.UserRole) == session:
                window.sessions.setCurrentRow(index)
                break
        else:
            raise AssertionError('Missing golden case')
        pane = window.facts.handover

        assert all(label.text() == '待生成' for label in pane.field_labels.values())
        pane.update_local()
        assert not pane.full_summary.isHidden()
        assert set(pane.field_labels) == set(FIELDS)
        assert all(label.text() != '待生成' for label in pane.field_labels.values())
        button_texts = [button.text() for button in pane.findChildren(QPushButton)]
        assert button_texts.count('查看依据') == 4
        assert button_texts.count('修改接手要点') == 1
        labels = {label.text() for label in pane.findChildren(QLabel)}
        assert {'客户当前诉求：', '前期沟通情况：', '待确认内容：', '建议处理方式：'} <= labels
        summary = pane.reply_summary()
        assert all(i['refs'] and all(r in summary['evidence'] for r in i['refs']) for i in summary['items'])
        context = reply_context(window.result, '', summary=summary)
        assert len(context['handover']['items']) == len(summary['items'])
        if session == 'S00001':
            assert '实际发出' in pane.field_labels['待解决'].text()
            tasks = pane.checklist.items(session)
            assert any('实际发出' in item['text'] for item in tasks)
            assert any('收到补发商品' in item['text'] for item in tasks)
            first = tasks[0]
            pane.checklist.edit(first['id'], '核实补发物流是否实际发出', '验收客服')
            screenshot = output / 'synthetic-proof.png'
            Image.new('RGB', (32, 32), 'white').save(screenshot)
            pane.checklist.attach(first['id'], screenshot, '验收客服')
            pane.checklist.set_done(first['id'], True, '验收客服')
            pane.checklist_widget.reload()
            assert pane.checklist.items(session)[0]['done'] == 1
            capture(window, 'checklist-S00001.png')
        else:
            assert 'P0' in pane.urgent.text()
        capture(window, 'handover-' + session + '.png')
        handover_checks.append({'session': session, 'four_fields_visible': True,
                                'evidence_resolves': True, 'reply_context_connected': True})
        dialog = ReportDialog(window)
        dialog.selection.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.reason.setPlainText('验收示例：请主任协助核实消费者诉求')
        capture(dialog, 'report-' + session + '.png')
        dialog.submit_button.click()

    # Reproduce a completed summary worker followed by a session switch.
    # The model response is local and synthetic; no workbook content is sent.
    prior_settings, prior_key = dict(window.settings), window.api_key
    prior_generate, prior_exec = handover.generate_summary, QMessageBox.exec
    try:
        window.settings.update(base_url='http://localhost:9000/v1', model='test')
        window.api_key = 'test-key'
        handover.generate_summary = lambda summary, config: dict(summary, source='模型概括 · 待人工核对')
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
        for index in range(window.sessions.count()):
            if window.sessions.item(index).data(Qt.ItemDataRole.UserRole) == 'S00052':
                window.sessions.setCurrentRow(index)
                break
        window.facts.handover.update_button.click()
        worker = window.summary_worker
        assert worker is not None and worker.wait(3000)
        QApplication.processEvents()
        for index in range(window.sessions.count()):
            if window.sessions.item(index).data(Qt.ItemDataRole.UserRole) == 'S00053':
                window.sessions.setCurrentRow(index)
                break
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Cancel
        window.facts.handover.generate_model()
    finally:
        handover.generate_summary, QMessageBox.exec = prior_generate, prior_exec
        window.settings, window.api_key = prior_settings, prior_key
    assert len(ReportStore(window.store).reports()) == 2
    window.tabs.setCurrentIndex(1)
    assert window.task_list.count() == 2
    capture(window, 'director.png')
    browser = AllChatsDialog(window, 'S00001')
    assert browser.sessions.count() == len(window.provider.sessions())
    capture(browser, 'all-chats.png')
    browser.close()
    report = window.reports.reports()[0]
    handler = HandleReportDialog(window, report)
    assert handler.findChildren(ReadOnlyChecklist)
    assert handler.checklist_rows and any(item['done'] for item in handler.checklist_rows)
    handler.note.setText('验收记录：主任已完成核实')
    handler.status.setCurrentText('已处理')
    capture(handler, 'handle.png')
    handler.save()
    assert window.task_list.count() == 1
    assert len(window.reports.events(report['id'])) == 2
    (output / 'result.json').write_text(json.dumps({
        'passed': True, 'sessions': ['S00268', 'S00001'],
        'all_chats': len(window.provider.sessions()), 'explicit_reports': 2,
        'pending_after_handling': 1, 'ordinary_reply_reports': 0,
        'handover_checks': handover_checks, 'live_model_called': False,
        'summary_after_session_switch': True,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
