"""Conservative duplicate-question gate; all unresolved cases need staff review."""
from copy import deepcopy
import re

AMBIGUOUS = re.compile(r'[?？“”「」"]|是否|会不会|是不是|如果|假如|可能|不确定|不记得|记不清|不是|并非|没说|没有说|说错|更正|朋友|家人|孩子|他说|她说|医生说|客服说')
SYMPTOM = re.compile(r'红肿|刺痛|发红|不适|过敏|瘙痒|起疹')
CURRENT = re.compile(r'(?:到现在|现在|目前)(?:已经)?(?:没有加重也没减轻|没有加重也没有减轻|缓解(?:了一些|一些|了)?|加重了|没变化|没有变化)(?=[，。！；,;!\s]|$)')
ONSET = re.compile(r'(?:昨天|昨晚|今天|今早|前天)(?:上午|下午|晚上)?(?:[零一二三四五六七八九十两\d]+点(?:半)?)(?:开始|起)(?=[，。！；,;!\s]|红肿|刺痛|发红|不适|过敏|瘙痒|起疹|$)')


def existing_answer(kind, context):
    buyers = [m for m in context.get('messages', []) if m.get('role') == '买家']
    if kind not in {'onset', 'current_change'} or not buyers:
        return None
    # Older current-state statements may be stale; no automatic suppression.
    candidates = buyers[-1:] if kind == 'current_change' else buyers
    if any(AMBIGUOUS.search(m.get('text', '')) for m in candidates):
        return None
    found = []
    for message in candidates:
        text = message.get('text', '')
        if not SYMPTOM.search(text):
            continue
        match = (CURRENT if kind == 'current_change' else ONSET).search(text)
        if match:
            found.append({'ref': message['ref'], 'quote': match.group(), 'source': 'consumer_report'})
    if kind == 'onset' and len({e['quote'] for e in found}) > 1:
        return None
    return found or None


def gate_questions(rows, context):
    suppressed, pending = [], []
    for row in rows:
        evidence = existing_answer(row.get('type'), context)
        if evidence:
            suppressed.append({'candidate': deepcopy(row), 'reason': 'explicit_answer_already_in_source',
                               'answer_evidence': evidence})
        else:
            pending.append({'candidate': deepcopy(row), 'reason': 'necessity_or_existing_answer_needs_staff_review'})
    return {'suppressed': suppressed, 'pending_staff_review': pending,
            'customer_ready_questions': [], 'automatic_reply_allowed': False}
