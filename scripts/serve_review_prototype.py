"""Local, disposable review sample. Run: .venv/Scripts/python scripts/serve_review_prototype.py"""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_task_selection_live import validate


def build_cases():
    cases = []
    selections = [
        ('task-selection-live-20261001', 'S00001_4', '商品破损 · 已接受换货', False),
        ('task-selection-live-20261001', 'S00268_0', '报告不适 · 首次沟通', False),
        ('task-boundaries-live-20261001', 'BOUNDARY_KNOWN_SYMPTOMS', '重复补问 · 已说明当前变化', True),
    ]
    for folder, case_id, title, synthetic in selections:
        directory = ROOT / '.scratch' / folder
        request = json.loads((directory / 'requests.json').read_text(encoding='utf-8'))
        source = next(r for r in request['cases'] if r['id'] == case_id)
        saved = json.loads((directory / f'{case_id}.json').read_text(encoding='utf-8'))
        result = validate(saved['parsed'], source['context'])
        items = []
        for kind, rows in [('处理事项', result['proposed_task_preview']),
                           ('补问前核实', result['proposed_staff_reminders'])]:
            items.extend(dict(row, kind=kind, suppressed=False) for row in rows)
        for conflict in result['question_conflicts']['suppressed']:
            items.append(dict(conflict['candidate'], kind='已拦下的补问', suppressed=True,
                              answer_evidence=conflict['answer_evidence']))
        fingerprint = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        case = dict(id=case_id, title=title, synthetic=synthetic, source=source,
                    source_sha256=fingerprint, items=items)
        review_path = ROOT / '.scratch' / 'review-user-confirmed' / f'{case_id}.json'
        if review_path.exists():
            review = json.loads(review_path.read_text(encoding='utf-8'))
            # Chat confirmation applies only to these exact sources and suggestions.
            if (review.get('source_sha256') == fingerprint
                    and review.get('original_items') == items
                    and len(review.get('decisions', [])) == len(items)
                    and all(d in ('keep', 'drop') for d in review['decisions'])):
                case['chat_review'] = review
        cases.append(case)
    return cases


def page():
    data = json.dumps(build_cases(), ensure_ascii=False).replace('<', '\\u003c')
    return (ROOT / 'scripts' / 'review_prototype.html').read_text(encoding='utf-8').replace('__CASE_DATA__', data).encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/', '/review'):
            self.send_error(404)
            return
        body = page()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8769), Handler)
    print('Review prototype: http://127.0.0.1:8769/review', flush=True)
    server.serve_forever()
