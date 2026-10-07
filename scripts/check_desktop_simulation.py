"""Visible acceptance with isolated records and explicitly fake reply/summary models."""
import copy
import json
import sys
import tempfile
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
from desktop.simulation import SimulationWindow


def fake_reply(result, config, **kwargs):
    if result['risk']['level'] == 'P0':
        return {'status': 'model', 'text': '（测试模型）收到您的退款诉求和红肿刺痛反馈，建议优先由专业售后处理人员核实。'}
    return {'status': 'model', 'text': '（测试模型）收到您反馈的瓶身破损和换货诉求，我会协助核实。请描述一下具体破损情况。'}


def fake_summary(pending, config):
    result = copy.deepcopy(pending)
    result['source'] = '测试模型摘要 · 仅验证程序流程'
    return result


def main():
    output = ROOT / '.scratch' / 'desktop-simulation'
    output.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory()
    directory = Path(temp.name)
    app = QApplication([])
    app.setStyle('Fusion')
    normal = MainWindow(ExcelProvider(), ReviewStore(directory / 'normal.sqlite3'),
                        {'base_url': 'https://example.invalid/v1', 'model': 'fake'}, directory, 'fake')
    normal.show()
    checks = {}
    def idle(w):
        for _ in range(200):
            QTest.qWait(10)
            if not w.busy():
                return
        raise AssertionError('Worker timeout')
    def send(w, text):
        w.customer_input.setPlainText(text)
        QTest.mouseClick(w.customer_send, Qt.MouseButton.LeftButton)
        idle(w)
    def check():
        try:
            for sid in ('S00001', 'S00268'):
                for i in range(normal.sessions.count()):
                    if normal.sessions.item(i).data(Qt.ItemDataRole.UserRole) == sid:
                        normal.sessions.setCurrentRow(i)
                        break
                QTest.qWait(100)
                assert normal.result['case']['session_id'] == sid
                if sid == 'S00268':
                    assert normal.result['risk']['level'] == 'P0'
            checks['normal_sessions'] = ['S00001', 'S00268']
            QTest.mouseClick(normal.settings_nav, Qt.MouseButton.LeftButton)
            QTest.qWait(150)
            assert normal.settings_menu.isVisible()
            assert normal.grab().save(str(output / 'settings-menu.png'))
            menu = normal.settings_menu
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(normal.simulation_action).center())
            w = normal.simulation_window
            QTest.qWait(200)
            assert w.customer_input.isVisible() and w.customer_send.isVisible()
            checks['settings_menu_entry'] = True
            send(w, '收到的瓶子破了，我要换货。')
            assert len(w.chat.messages) == 2
            assert not w.facts.handover.raw.get('source')
            w.facts.handover.update_button.click()
            idle(w)
            assert w.facts.handover.raw.get('source')
            send(w, '我不换了，我要退款，而且用了之后脸红肿刺痛。')
            assert w.result['risk']['level'] == 'P0'
            assert [m['角色'] for m in w.chat.messages] == ['买家', '客服', '买家', '客服']
            assert [r.outgoing for r in w.chat.rows] == [True, False, True, False]
            assert w.facts.handover.source_changed()
            assert w.grab().save(str(output / 'summary-stale.png'))
            w.facts.handover.update_button.click()
            idle(w)
            assert not w.facts.handover.source_changed()
            QTest.qWait(350)
            assert w.grab().save(str(output / 'multiturn.png'))
            w.resize(1040, 640)
            QTest.qWait(250)
            assert w.customer_send.isVisible()
            assert w.grab().save(str(output / 'narrow.png'))
            sid = w.session
            w.customer_input.setPlainText('尚未发送的客户输入')
            assert w.close()
            restored = SimulationWindow(directory / 'simulation', normal.settings, 'fake')
            restored.show()
            QTest.qWait(200)
            assert len(restored.provider.messages(sid)) == 4
            assert restored.customer_input.toPlainText() == '尚未发送的客户输入'
            restored.new_test_button.click()
            QTest.qWait(200)
            assert restored.result is None
            assert restored.grab().save(str(output / 'blank.png'))
            checks.update(passed=True, automatic_multiturn=True, customer_on_right=True,
                          risk='P0', explicit_summary=True, summary_stale_and_updated=True,
                          restart_restored=True, blank_test=True, api_calls=network.call_count,
                          model='explicit fake models; no live quality claim')
            assert network.call_count == 0
            (output / 'result.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
            if '--keep-open' in sys.argv:
                restored.setWindowTitle('共情副驾 · 模拟对话测试（隔离验收·假模型）')
                normal.simulation_window = restored
                app._acceptance_window = restored
                return
            restored.close()
            normal.close()
            app.exit(0)
        except Exception:
            import traceback
            (output / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            app.exit(1)
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No live API')) as network, \
         patch('desktop.simulation.generate_reply', side_effect=fake_reply), \
         patch('desktop.handover.generate_summary', side_effect=fake_summary):
        QTimer.singleShot(500, check)
        return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
