"""Revalidate saved task selections offline; no API client is invoked."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_task_selection_live import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / '.scratch').resolve()):
        parser.error('Output must be in .scratch')
    records, hashes = [], {}
    with patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden')) as network:
        for folder in ('task-selection-live-20261001', 'task-boundaries-live-20261001'):
            directory = ROOT / '.scratch' / folder
            request = json.loads((directory / 'requests.json').read_text(encoding='utf-8'))
            for path in directory.glob('*.json'):
                hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            for row in request['cases']:
                saved = json.loads((directory / (row['id'] + '.json')).read_text(encoding='utf-8'))
                checked = validate(saved['parsed'], row['context'])
                assert checked['proposed_task_preview'] == saved['validation']['proposed_task_preview']
                assert checked['draft_action'] == 'preserve'
                assert not checked['automatic_reply_allowed']
                records.append({'id': row['id'], 'source': folder, 'recheck': checked})
        assert network.call_count == 0
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == h for path, h in hashes.items())
    target = next(r for r in records if r['id'] == 'BOUNDARY_KNOWN_SYMPTOMS')['recheck']
    assert [r['candidate']['type'] for r in target['question_conflicts']['suppressed']] == ['current_change']
    assert 'medical_material' in [r['type'] for r in target['proposed_staff_reminders']]
    output = {'api_calls': 0, 'source_hashes_unchanged': True, 'source_hashes': hashes,
              'cases': records, 'suppressed_count': sum(len(r['recheck']['question_conflicts']['suppressed']) for r in records)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'cases': len(records), 'suppressed_count': output['suppressed_count'], 'api_calls': 0}))


if __name__ == '__main__':
    main()
