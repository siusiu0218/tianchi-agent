"""Offline replay of saved outputs + explicitly authored typed replacements."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot.task_guard_prototype import review_tasks


def examples(source):
    requests = json.loads((source / 'requests.json').read_text(encoding='utf-8'))
    # Source-reviewed fixtures, not an automatic conversion of model prose.
    specs = {
        'S00001_0': ({'verify_product': ['M1']}, {'order': ['S1']}),
        'S00001_4': ({'verify_exchange': ['M4', 'M5']}, {'order': ['S1'], 'image': ['M3']}),
        'S00268_0': ({'verify_discomfort': ['M1']}, {'order': ['S1']}),
        'S00268_8': ({'verify_discomfort': ['M1'], 'verify_refund': ['M4', 'M5'],
                       'verify_reimbursement': ['M4', 'M5'], 'verify_callback': ['M4', 'M5', 'M8']},
                      {'order': ['S1'], 'medical_material': ['M3'], 'account': ['M7'], 'medication': ['M7']}),
    }
    for row in requests['cases']:
        scope, provided = specs[row['id']]
        messages = row['context']['messages'] + row['context']['system_sources']
        context = {'messages': messages, 'scope_origin': 'source_reviewed', 'scope': scope,
                   'provided': provided, 'risk_level': row['context']['risk_level']}
        text = {m['ref']: m['text'] for m in messages}
        typed = {'tasks': [{'type': task, 'evidence': [{'ref': ref, 'quote': text[ref]} for ref in refs]}
                           for task, refs in scope.items()], 'questions': []}
        raw = json.loads((source / (row['id'] + '.json')).read_text(encoding='utf-8'))
        yield row['id'], raw['parsed'], typed, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.scratch/state-extraction-v2-live-20261001')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / '.scratch').resolve()):
        parser.error('Output must remain in ignored .scratch')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.source.glob('*.json')}
    rows = []
    for name, raw, typed, context in examples(args.source):
        original = review_tasks(raw, context, '保留手写原稿')
        corrected = review_tasks(typed, context, '保留手写原稿')
        assert original['status'] == 'blocked' and original['draft'] == '保留手写原稿'
        assert corrected['status'] == 'needs_human_review' and not corrected['automatic_reply_allowed']
        rows.append({'id': name, 'legacy_tasks': raw['current_tasks'], 'legacy_result': original,
                     'replacement_origin': 'manually_authored_typed_fixture_not_model_regeneration',
                     'typed_candidate': typed, 'reviewed_context': context, 'corrected_result': corrected})
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.source.glob('*.json')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump({'api_calls': 0, 'original_hashes': before, 'cases': rows}, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'old_outputs_blocked': len(rows), 'typed_previews_need_human_review': len(rows), 'api_calls': 0}))


if __name__ == '__main__':
    main()
