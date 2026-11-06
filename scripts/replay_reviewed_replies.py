"""Offline MOCK replay with explicitly source-reviewed plans; no live model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot.data import ExcelProvider, DEFAULT_SOURCE
from copilot.rag_prototype import Query
from copilot.rag_reply_prototype import prepare, propose, ReviewedReplyPlan
from scripts.rag_reply_prototype import good


def replay():
    before = hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest()
    provider = ExcelProvider()
    results = []
    # Plans reviewed against these source cutoffs, not inferred from session IDs by production logic.
    for session, index, focus, stage, missing in [
        ('S00001', 0, 'exchange', 'initial_report', ()),
        ('S00001', 4, 'exchange', 'plan_accepted', ()),
        ('S00268', 0, 'compensation', 'initial_report', ('onset', 'current_change')),
        ('S00268', 8, 'compensation', 'plan_accepted', ())]:
        messages = provider.messages(session)
        cutoff = messages[index]['发送时间']
        case = provider.get_case(session, cutoff)
        plan = ReviewedReplyPlan(focus, tuple(m['message_id'] for m in case['messages']), missing)
        query = Query('核对当前处理事项', 'case', 'LOCAL_MOCK_WORKBOOK',
                      'damage_exchange' if focus == 'exchange' else 'adverse_followup',
                      stage, cutoff.replace(' ', 'T') + '+08:00', session, session,
                      frozenset({'plan_accepted'}) if stage == 'plan_accepted' else frozenset())
        def snapshot():
            return prepare(case, query, [], '保留原稿', reply_plan=plan)
        prepared = snapshot()
        result = propose(prepared, good, snapshot)
        assert result['status'] == 'preview' and result['draft'] == '保留原稿'
        assert result['risk_level'] == ('P0' if session == 'S00268' else 'P1')
        assert all(s['message_id'] in plan.source_refs for c in result['citations'] for s in c['sources'])
        if focus == 'compensation':
            assert '换货' not in result['suggestion']
            assert result['suggestion'].startswith('您反馈的不适')
        if stage == 'plan_accepted':
            assert '什么时候' not in result['suggestion'] and '请提供' not in result['suggestion']
        results.append({'session': session, 'cutoff': cutoff, 'stage': stage,
                        'caller_reviewed_focus': focus, 'messages': case['messages'], 'result': result})
    assert hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest() == before
    return {'source_sha256': before, 'source_unchanged': True, 'live_model_calls': 0,
            'scope': 'manual plan + deterministic selection on existing MOCK; no semantic quality score',
            'replays': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload = replay()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False))
