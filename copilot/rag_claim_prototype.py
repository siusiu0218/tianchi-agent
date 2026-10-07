"""EXPERIMENTAL free-text claim audit. Zero findings NEVER means approved.

Evidence assertions are caller-reviewed inputs, not facts extracted by a model.
Patterns cover selected known errors only; semantic support still needs a person.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from copilot.rag_prototype import moment


@dataclass(frozen=True)
class Evidence:
    id: str
    origin: str
    session: str
    available_at: str
    assertions: tuple[tuple[str, str], ...]


def number(text):
    text = unicodedata.normalize('NFKC', text)
    try:
        return Decimal(text)
    except InvalidOperation:
        digits = dict(zip('零一二三四五六七八九', range(10)))
        digits.update({'两': 2, '〇': 0})
        if text and all(char in digits for char in text):
            return Decimal(''.join(str(digits[char]) for char in text))
        total = current = 0
        for char in text:
            if char in digits:
                current = digits[char]
            elif char in '十百千':
                total += (current or 1) * {'十': 10, '百': 100, '千': 1000}[char]
                current = 0
            else:
                raise ValueError('Unsupported numeral')
        return Decimal(total + current)


NUM = r'(?:[+-]?\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千]+)'
MONEY_FIELDS = {'refund_amount', 'compensation_amount'}
TIME_FIELDS = {'historical_dispatch_hours'}
EXECUTION = {
    'refund_completed': r'已(?:经)?退款|退款已到账|已退回款项',
    'replacement_dispatched': r'已(?:经)?发货|已(?:经)?发出新品',
    'replacement_received': r'已(?:经)?签收|已收到新品',
}


def audit(output, evidence, *, session, cutoff, context_id, draft='', risk_level='P1'):
    """Reject explicit unsupported claims; otherwise ALWAYS require human review.

    Current execution events need current_business evidence. Statements reported
    in chat use a different predicate, e.g. staff_reported_dispatch. Case and
    policy assertions can never substantiate facts about the current customer.
    """
    issues = []
    base = {'draft': draft, 'suggestion': '', 'risk_level': risk_level,
            'action_status': 'review_only', 'auto_approved': False}
    if (not isinstance(output, dict) or set(output) != {'context_id', 'sentences'}
            or output.get('context_id') != context_id):
        return {**base, 'status': 'blocked', 'issues': ['invalid_response_or_snapshot']}
    rows = output['sentences']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        return {**base, 'status': 'blocked', 'issues': ['invalid_sentences']}
    sources = {e.id: e for e in evidence}
    if len(sources) != len(evidence):
        raise ValueError('Duplicate evidence IDs')
    texts = []
    citations = []
    for index, row in enumerate(rows):
        prefix = f'sentence_{index + 1}:'
        if (not isinstance(row, dict) or set(row) != {'text', 'claims'}
                or not isinstance(row['text'], str) or not row['text'].strip()
                or not isinstance(row['claims'], list) or len(row['claims']) > 20):
            issues.append(prefix + 'invalid_sentence')
            continue
        text = unicodedata.normalize('NFKC', row['text'])
        texts.append(row['text'])
        supported = []
        for claim in row['claims']:
            if (not isinstance(claim, dict) or set(claim) != {'field', 'value', 'refs'}
                    or not all(isinstance(claim[k], str) for k in ('field', 'value'))
                    or not isinstance(claim['refs'], list) or not claim['refs']
                    or any(not isinstance(ref, str) for ref in claim['refs'])):
                issues.append(prefix + 'invalid_claim')
                continue
            field, value = claim['field'], claim['value']
            valid = True
            for ref in claim['refs']:
                source = sources.get(ref)
                if source is None:
                    issues.append(prefix + 'unknown_reference')
                    valid = False
                elif (source.session != session or source.origin not in {'current_chat', 'current_business'}
                      or moment(source.available_at) > moment(cutoff)):
                    issues.append(prefix + 'ineligible_source')
                    valid = False
                elif (field, value) not in source.assertions:
                    issues.append(prefix + 'unsupported_field_value')
                    valid = False
                elif field in EXECUTION and source.origin != 'current_business':
                    issues.append(prefix + 'chat_is_not_execution_evidence')
                    valid = False
            if valid:
                supported.append((field, value))
                citations.append({'sentence': index + 1, **claim})
        # Number matching is sentence-local and unit-aware, not a search over the
        # entire conversation or all retrieved cases. Unknown phrasing is reviewed.
        for pattern, fields, scale in [(rf'({NUM})\s*元', MONEY_FIELDS, Decimal(1)),
                                       (rf'({NUM})\s*小时', TIME_FIELDS, Decimal(1)),
                                       (rf'({NUM})\s*天', TIME_FIELDS, Decimal(24))]:
            for found in re.finditer(pattern, text):
                try:
                    value = number(found.group(1)) * scale
                    matches = any(field in fields and number(v) == value for field, v in supported)
                except (ValueError, InvalidOperation):
                    matches = False
                if not matches:
                    issues.append(prefix + 'unsupported_number_or_unit')
        for field, pattern in EXECUTION.items():
            if re.search(pattern, text) and (field, 'true') not in supported:
                issues.append(prefix + 'unsupported_execution')
        for label, field in [('补偿', 'compensation_amount'), ('退款', 'refund_amount')]:
            for found in re.finditer(rf'{label}\s*({NUM})\s*元', text):
                try:
                    supported_role = any(f == field and number(v) == number(found.group(1)) for f, v in supported)
                except (ValueError, InvalidOperation):
                    supported_role = False
                if not supported_role:
                    issues.append(prefix + 'money_role_mismatch')
        if re.search(r'(保证|承诺|一定|确保|为您安排).{0,16}(小时|天|退款|补偿|发货)', text):
            issues.append(prefix + 'new_commitment_requires_authorization')
        if re.search(r'保证安全|诊断为|绝不会过敏|建议服用|建议用药', text):
            issues.append(prefix + 'medical_or_safety_claim')
    full_text = ''.join(texts)
    if len(full_text) > 800:
        issues.append('reply_too_long')
    if risk_level == 'P0' and not ('不适' in full_text and '专业' in full_text):
        issues.append('missing_p0_followup')
    return {**base, 'status': 'blocked' if issues else 'needs_human_review',
            'suggestion': '' if issues else full_text,
            'issues': sorted(set(issues)), 'citations': citations,
            'semantic_support_verified': False}
