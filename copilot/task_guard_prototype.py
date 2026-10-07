"""Offline task preview contract. Never emits model-authored prose or sends replies.

The caller supplies independently reviewed task scope and provided-information
state. Quote existence is not semantic verification; every preview needs review.
"""
from copy import deepcopy

TASKS = {
    'verify_product': '核实商品问题及适用的售后处理方式。',
    'verify_discomfort': '优先核实消费者报告的不适，并由人工确认后续处理。',
    'verify_exchange': '核对此前换货安排及实际进度。',
    'verify_refund': '核对此前退款安排及实际进度。',
    'verify_reimbursement': '核对此前费用报销安排及已有票据记录；材料要求另行核实。',
    'verify_callback': '核对此前回访安排及实际进度；历史时限不作新的保证。',
}
QUESTIONS = {
    'order': '请客服先检查订单关联情况，再决定是否需要客户提供订单信息。',
    'image': '请客服先检查已有图片记录与可访问性，再决定是否需要补图。',
    'medical_material': '请客服先检查已有资料及可访问性，再决定是否需要补充。',
    'account': '请客服先检查已有收款信息，再决定是否需要补充。',
    'medication': '请客服先检查已提供信息；此提示不提供用药建议。',
    'onset': '请客服核对不适发生时间是否已有记录；确认缺失且必要后再询问。',
    'current_change': '请客服核对当前情况变化是否已有记录；确认缺失且必要后再询问。',
}


def review_tasks(candidate, context, draft=''):
    """context.scope maps allowed task IDs to source-reviewed message refs.

provided maps information types to refs; absence means unknown, not not-submitted.
Context is a caller trust boundary, not an LLM output. No runtime state mutation.
"""
    base = {'status': 'blocked', 'draft': draft, 'task_preview': [], 'staff_reminders': [],
            'issues': [], 'automatic_reply_allowed': False, 'semantic_verified': False}
    try:
        messages = {m['ref']: m for m in context['messages']}
        if context.get('scope_origin') != 'source_reviewed':
            raise ValueError('scope_not_reviewed')
        if set(context['scope']) - set(TASKS) or set(context['provided']) - set(QUESTIONS):
            raise ValueError('invalid_reviewed_scope')
        for refs in list(context['scope'].values()) + list(context['provided'].values()):
            if not isinstance(refs, list) or not refs or any(r not in messages for r in refs):
                raise ValueError('invalid_reviewed_refs')
        if not isinstance(candidate, dict) or set(candidate) != {'tasks', 'questions'}:
            raise ValueError('free_text_or_legacy_shape_not_allowed')
        if not isinstance(candidate['tasks'], list) or not candidate['tasks'] or len(candidate['tasks']) > len(TASKS):
            raise ValueError('invalid_task_list')
        if not isinstance(candidate['questions'], list) or len(candidate['questions']) > len(QUESTIONS):
            raise ValueError('invalid_question_list')
        seen = set()
        rendered = []
        reminders = []
        for field, table in [('tasks', TASKS), ('questions', QUESTIONS)]:
            for row in candidate[field]:
                if not isinstance(row, dict) or set(row) != {'type', 'evidence'}:
                    raise ValueError('free_text_not_allowed')
                kind = row['type']
                if not isinstance(kind, str) or kind not in table or (field, kind) in seen:
                    raise ValueError('unknown_or_duplicate_type')
                seen.add((field, kind))
                ev = row['evidence']
                if not isinstance(ev, list) or not ev:
                    raise ValueError('evidence_required')
                for item in ev:
                    if not isinstance(item, dict) or set(item) != {'ref', 'quote'}:
                        raise ValueError('invalid_evidence')
                    if (not isinstance(item['ref'], str) or item['ref'] not in messages
                            or not isinstance(item['quote'], str) or not item['quote'].strip()
                            or item['quote'] not in messages[item['ref']]['text']):
                        raise ValueError('invalid_quote_or_ref')
                refs = {e['ref'] for e in ev}
                if field == 'tasks':
                    if kind not in context['scope'] or not set(context['scope'][kind]) <= refs:
                        raise ValueError('task_outside_reviewed_scope')
                    rendered.append({'type': kind, 'text': table[kind], 'evidence': deepcopy(ev)})
                else:
                    if kind in context['provided']:
                        raise ValueError('already_provided_check_internally')
                    reminders.append({'type': kind, 'text': table[kind], 'evidence': deepcopy(ev)})
        if context['risk_level'] == 'P0':
            if 'verify_discomfort' not in [r['type'] for r in rendered]:
                raise ValueError('missing_p0_task')
            rendered.sort(key=lambda r: r['type'] != 'verify_discomfort')
            for kind in ('onset', 'current_change'):
                if kind not in context['provided'] and ('questions', kind) not in seen:
                    reminders.append({'type': kind, 'text': QUESTIONS[kind],
                                      'reason': 'source_review_did_not_confirm_this_information',
                                      'source_refs': context['scope']['verify_discomfort'][:]})
        return {**base, 'status': 'needs_human_review', 'task_preview': rendered, 'staff_reminders': reminders}
    except (KeyError, TypeError, ValueError) as exc:
        return {**base, 'issues': [str(exc) if isinstance(exc, ValueError) else 'invalid_input']}
