"""EXPERIMENTAL constrained reply selection, disconnected from desktop and APIs.

The model selects program-authored segment IDs; arbitrary generated prose is not
accepted. This verifies boundaries, NOT free-form generation quality. Stage and
retrieval prerequisites remain caller-established, as in rag_prototype.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json

from copilot.agent import assess
from copilot.rag_prototype import moment, retrieve


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=sorted)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ReviewedReplyPlan:
    """Caller-reviewed context, never an automatic semantic classification."""
    focus: str
    source_refs: tuple[str, ...]
    missing_details: tuple[str, ...] = ()


def prepare(case, query, documents, draft='', *, reply_plan=None):
    """Build an immutable-by-convention snapshot; no source is an instruction.

    Input case follows ExcelProvider's schema. Time strings lacking an offset in
    that existing schema are interpreted as Asia/Shanghai (+08:00).
    """
    def at(value):
        return moment(value.replace(' ', 'T') + '+08:00') if len(value) == 19 else moment(value)

    if case['session_id'] != query.session or at(case['cutoff']) != moment(query.at):
        raise ValueError('Case and query snapshot mismatch')
    if not isinstance(draft, str):
        raise ValueError('Draft must be text')
    messages = case['messages']
    refs = [m['message_id'] for m in messages]
    if any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != len(refs):
        raise ValueError('Invalid current-message references')
    if any(at(m['发送时间']) > moment(query.at) for m in messages):
        raise ValueError('Future message in current case')
    risk = assess(case)
    retrieval = retrieve(documents, query)
    evidence = {}
    current = []
    for index, message in enumerate(messages):
        alias = f'C{index + 1}'
        evidence[alias] = {'session': case['session_id'], 'message_id': message['message_id']}
        current.append({'ref': alias, 'role': message['角色'], 'text': message['message_text']})
    buyer_refs = [row['ref'] for row in current if row['role'] == '买家']
    options = [
        {'id': 'ack', 'text': '理解您希望尽快处理商品问题的心情。', 'refs': buyer_refs,
         'kind': 'service_language'},
    ]
    if query.stage in {'initial_report', 'evidence_received', 'plan_proposed'}:
        options.append({'id': 'verify_issue', 'text': '我会协助核实商品情况及适用的售后安排。',
                        'refs': buyer_refs, 'kind': 'verification_plan'})
    else:
        options.append({'id': 'verify_progress', 'text': '我会核对此前沟通的换货安排及实际进度；若涉及旧品寄回或运费，再核实适用的处理方式。',
                        'refs': buyer_refs, 'kind': 'verification_plan'})
    required = [row['id'] for row in options]
    image_refs = [f'C{i+1}' for i, m in enumerate(messages) if m.get('image_path') or m.get('内容类型') == '图片']
    if image_refs:
        options.append({'id': 'existing_image', 'text': '记录中已有图片消息，我会先核对附件是否可查看。',
                        'refs': image_refs, 'kind': 'current_record'})
        required.append('existing_image')
    if retrieval['status'] != 'matched' and query.kind in {'policy', 'product'}:
        text = ('资料版本存在冲突，适用说明需要进一步核实。' if retrieval['status'] == 'conflict'
                else '目前资料不足以确认适用的商品说明或售后政策，需要进一步核实。')
        options.append({'id': 'knowledge_gap', 'text': text, 'refs': [], 'kind': 'retrieval_gap'})
        required.append('knowledge_gap')
    if risk['level'] == 'P0':
        risk_ids = {row['message_id'] for row in risk['evidence']}
        risk_refs = [alias for alias, source in evidence.items() if source['message_id'] in risk_ids]
        options.append({'id': 'priority_discomfort',
                        'text': '您反馈的不适需要优先核实，建议由专业售后处理人员跟进。',
                        'refs': risk_refs, 'kind': 'risk_followup'})
        required.append('priority_discomfort')
    if reply_plan is not None:
        if (reply_plan.focus not in {'exchange', 'compensation'}
                or not reply_plan.source_refs
                or not set(reply_plan.source_refs) <= set(refs)
                or not set(reply_plan.missing_details) <= {'onset', 'current_change'}):
            raise ValueError('Invalid reviewed reply plan')
        plan_refs = [alias for alias, source in evidence.items()
                     if source['message_id'] in reply_plan.source_refs]
        accepted = query.stage == 'plan_accepted'
        if reply_plan.focus == 'exchange':
            text = ('我先核对此前的换货安排和目前的处理进度；如还需要您补充信息，会具体说明。'
                    '若涉及旧品寄回或运费，也会一并核实。' if accepted else
                    '我先核实您反馈的商品问题及适用的售后处理方式，再和您确认后续安排。')
        else:
            text = ('我会核对此前沟通的退款、费用报销和回访安排及实际进度；'
                    '如果方案需要调整，会再和您确认。' if accepted else
                    '我先了解您的具体诉求，并核实适用的售后处理方案，再和您确认；'
                    '具体处理方式和补偿需要核实后才能答复。')
        preserved = [o for o in options if o['id'] in {'priority_discomfort', 'existing_image', 'knowledge_gap'}]
        # Risk response comes first; caller identifies only questions still unanswered.
        options = [o for o in preserved if o['id'] == 'priority_discomfort']
        if risk['level'] != 'P0':
            options.append({'id': 'ack', 'text': '理解您希望尽快处理商品问题的心情。',
                            'refs': buyer_refs, 'kind': 'service_language'})
        if risk['level'] == 'P0' and reply_plan.missing_details:
            questions = {'onset': '您提到的不适是什么时候开始的？',
                         'current_change': '目前的情况有没有变化？'}
            options.append({'id': 'clarify_discomfort',
                            'text': ''.join(questions[k] for k in dict.fromkeys(reply_plan.missing_details)),
                            'refs': plan_refs, 'kind': 'clarification'})
        options.append({'id': 'reviewed_next_step', 'text': text,
                        'refs': plan_refs, 'kind': 'verification_plan'})
        options += [o for o in preserved if o['id'] != 'priority_discomfort']
        required = [o['id'] for o in options]
    # Explicit projection: raw retrieved text, forbidden example values, account
    # fields and existing staff draft are never passed to this selection model.
    references = [{'id': hit['id'], 'kind': hit['kind'], 'version': hit['version'],
                   'use': hit['allowed_use'], 'points': hit['reference_points']}
                  for hit in retrieval['hits']]
    context = {'mode': 'select_segments_only', 'stage': query.stage,
               'current_messages_untrusted': current, 'risk_level': risk['level'],
               'retrieval_status': retrieval['status'], 'references_untrusted': references,
               'options': options, 'required_ids': required}
    snapshot_id = digest({'case': case, 'query': asdict(query), 'documents': [asdict(d) for d in documents],
                          'draft': draft, 'context': context})
    context['context_id'] = snapshot_id
    return {'context': context, 'context_id': snapshot_id, 'draft': draft,
            'risk': risk, 'retrieval': retrieval, 'evidence_map': evidence}


def validate_selection(output, prepared):
    if not isinstance(output, dict) or set(output) != {'context_id', 'segment_ids'}:
        return 'invalid_shape'
    if output['context_id'] != prepared['context_id']:
        return 'wrong_context'
    ids = output['segment_ids']
    options = prepared['context']['options']
    allowed = {row['id'] for row in options}
    if (not isinstance(ids, list) or not ids or len(ids) > len(options)
            or any(not isinstance(item, str) for item in ids)
            or len(ids) != len(set(ids)) or not set(ids) <= allowed):
        return 'invalid_segments'
    if not set(prepared['context']['required_ids']) <= set(ids):
        return 'missing_required'
    return None


def propose(prepared, model, current_snapshot):
    """model is an injected local callable; this module implements no API client.

    current_snapshot returns a freshly prepared snapshot at completion. Original
    or newly edited draft is preserved on every path; a valid proposal is preview
    only. No retries, auto-replacement, sending, or persistence.
    """
    snapshot = deepcopy(prepared)
    error = None
    try:
        # A malicious/misbehaving callable cannot mutate the validation snapshot.
        output = model(deepcopy(snapshot['context']))
        error = validate_selection(output, snapshot)
    except Exception:
        error = 'model_failure'
    try:
        latest = current_snapshot()
        if latest['context_id'] != snapshot['context_id']:
            return {'status': 'stale', 'reason': 'sources_or_draft_changed',
                    'draft': latest['draft'], 'suggestion': '', 'citations': [],
                    'risk_level': latest['risk']['level'], 'action_status': 'preview_only'}
    except Exception:
        return {'status': 'error', 'reason': 'snapshot_unavailable', 'draft': snapshot['draft'],
                'suggestion': '', 'citations': [], 'risk_level': snapshot['risk']['level'],
                'action_status': 'preview_only'}
    base = {'draft': latest['draft'], 'suggestion': '', 'citations': [],
            'risk_level': latest['risk']['level'], 'action_status': 'preview_only'}
    if error:
        return {**base, 'status': 'error', 'reason': error}
    selected = set(output['segment_ids'])
    # Program order, not model order, keeps stage/P0 notices stable.
    items = [row for row in snapshot['context']['options'] if row['id'] in selected]
    return {**base, 'status': 'preview', 'reason': 'human_review_required',
            'suggestion': ''.join(row['text'] for row in items),
            'citations': [{'segment_id': row['id'], 'kind': row['kind'],
                           'sources': [snapshot['evidence_map'][ref] for ref in row['refs']]}
                          for row in items]}
