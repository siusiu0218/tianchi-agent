"""Visible source acceptance with isolated state; leaves the reviewed UI open."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from copilot.data import ExcelProvider
from copilot.store import ReviewStore
from desktop.window import MainWindow
from desktop.suggestion_review import SuggestionReviewDialog


def main():
    output = ROOT / '.scratch' / 'desktop-suggestion-review'
    output.mkdir(exist_ok=True)
    app = QApplication([])
    provider = ExcelProvider()
    window = MainWindow(provider, ReviewStore(output / 'acceptance.sqlite3'), settings_directory=output)
    window.show()

    def check():
        try:
            results = []
            with patch('requests.sessions.Session.request', side_effect=AssertionError('No live API')) as network:
                for session in ('S00268', 'S00001'):
                    for i in range(window.sessions.count()):
                        if window.sessions.item(i).data(Qt.ItemDataRole.UserRole) == session:
                            window.sessions.setCurrentRow(i)
                            break
                    QApplication.processEvents()
                    pane = window.facts.handover
                    pane.update_local()
                    window.draft.setPlainText('验收草稿：审核待办不得覆盖这段文字。')
                    widget = pane.checklist_widget
                    assert widget.messages and widget.rows
                    from PySide6.QtWidgets import QPushButton
                    assert widget.findChild(QPushButton, 'reviewSuggestions') is not None
                    dialog = SuggestionReviewDialog(window, widget.store, session, widget.evidence, widget.messages)
                    dialog.show()
                    QApplication.processEvents()
                    assert provider.messages(session)[0]['message_text'] in dialog.sources.toPlainText()
                    dialog.editor.setPlainText(dialog.editor.toPlainText().replace('（本地验收修改）', '') + '（本地验收修改）')
                    dialog.keep.click()
                    assert '已保留' in dialog.status.text()
                    assert window.draft.toPlainText() == '验收草稿：审核待办不得覆盖这段文字。'
                    # Leave the visible example clean after verifying persistence.
                    row = dialog.rows[dialog.selector.currentIndex()]
                    clean = row['text'].replace('（本地验收修改）', '')
                    widget.store.edit(row['id'], clean, '验收还原', row['refs'])
                    dialog.rows = widget.store.items(session)
                    dialog.selector.setItemText(dialog.selector.currentIndex(), clean)
                    dialog.show_item()
                    QTest.qWait(150)
                    assert len(dialog.chat.rows) == len(provider.messages(session))
                    assert dialog.grab().save(str(output / (session + '.png')))
                    results.append({'session': session, 'saved': True, 'draft_preserved': True})
                    if session == 'S00268':
                        dialog.close()
                    else:
                        window.acceptance_dialog = dialog
                assert network.call_count == 0
            (output / 'result.json').write_text(json.dumps({'checks': results, 'api_calls': 0}, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            import traceback
            (output / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            app.exit(1)
    QTimer.singleShot(800, check)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
