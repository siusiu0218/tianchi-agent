"""EXPERIMENTAL: local retrieval logic, not connected to the application.

Question: can explicit metadata exclude unsuitable material before keyword ranking?
No model, database, customer reply, or business action. Case points require human
review; this module is not a general-purpose factuality or injection detector.
"""
from dataclasses import dataclass
from datetime import datetime


KINDS = {'case', 'policy', 'product'}
STAGES = {'initial_report', 'evidence_received', 'plan_proposed',
          'plan_accepted', 'execution_verification'}


def moment(value):
    """All prototype timestamps explicitly use +08:00 or another UTC offset."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a UTC offset')
    return parsed


@dataclass(frozen=True)
class Source:
    ref: str
    available_at: str
    text: str


@dataclass(frozen=True)
class Document:
    id: str
    kind: str
    version: str
    shop: str
    scenario: str
    stage: str
    available_at: str
    sources: tuple[Source, ...]
    search_terms: tuple[str, ...]
    points: tuple[str, ...]
    review: str = 'pending'
    synthetic: bool = False
    prerequisites: frozenset[str] = frozenset()
    session: str = ''
    group: str = ''
    product_id: str = ''
    product_version: str = ''
    valid_from: str = ''
    valid_until: str = ''
    forbidden_transfer: tuple[str, ...] = ()
    knowledge_key: str = ''
    reviewed_at: str = ''


@dataclass(frozen=True)
class Query:
    text: str
    kind: str
    shop: str
    scenario: str
    stage: str
    at: str
    session: str
    group: str
    conditions: frozenset[str] = frozenset()
    product_id: str = ''
    product_version: str = ''
    synthetic_mode: bool = False


def invalid_document(doc):
    ids = (doc.id, doc.version, doc.shop, doc.scenario)
    if not all(isinstance(s, str) and s.strip() for s in ids):
        return True
    if doc.kind not in KINDS or doc.stage not in STAGES:
        return True
    if not doc.sources or not doc.points or not doc.search_terms:
        return True
    if not all(isinstance(s, str) and s.strip() for s in (*doc.points, *doc.search_terms)):
        return True
    if doc.kind == 'case' and not all(isinstance(s, str) and s for s in (doc.session, doc.group)):
        return True
    if doc.kind == 'product' and not all(isinstance(s, str) and s for s in (doc.product_id, doc.product_version)):
        return True
    if doc.kind in {'policy', 'product'} and not doc.knowledge_key:
        return True
    try:
        available = moment(doc.available_at)
        if doc.review in {'approved', 'fixture_approved'} and moment(doc.reviewed_at) < available:
            return True
        for source in doc.sources:
            if not isinstance(source.ref, str) or not source.ref.strip() or not source.text.strip():
                return True
            if moment(source.available_at) > available:
                return True
        if doc.kind in {'policy', 'product'}:
            # Missing expiry is unknown, not implicitly valid forever.
            if moment(doc.valid_until) <= moment(doc.valid_from):
                return True
    except (ValueError, TypeError, AttributeError):
        return True
    return False


def exclusion(doc, query):
    if invalid_document(doc):
        return 'invalid_metadata'
    if doc.synthetic != query.synthetic_mode:
        return 'synthetic_mode_mismatch'
    expected_review = 'fixture_approved' if doc.synthetic else 'approved'
    if doc.review != expected_review:
        return 'not_reviewed'
    if doc.kind != query.kind:
        return 'wrong_source_type'
    if doc.shop != query.shop or doc.scenario != query.scenario:
        return 'wrong_scope'
    if doc.stage != query.stage:
        return 'wrong_stage'
    if not doc.prerequisites <= query.conditions:
        return 'prerequisites_missing'
    if max(moment(doc.available_at), moment(doc.reviewed_at)) > moment(query.at):
        return 'future_source'
    if doc.kind == 'case' and (doc.session == query.session or doc.group == query.group):
        return 'same_case_or_template_group'
    if doc.product_id and (doc.product_id != query.product_id or not query.product_version
                           or doc.product_version != query.product_version):
        return 'wrong_or_unknown_product_version'
    if doc.kind in {'policy', 'product'}:
        if not moment(doc.valid_from) <= moment(query.at) < moment(doc.valid_until):
            return 'outside_validity'
    return None


def retrieve(documents, query, limit=3):
    """Return reference points separately from raw evidence; never a customer reply.

    Ranking counts matched curated keywords, not correctness or confidence.
    Conditions/stage must be independently established by the caller, not a case.
    """
    if query.kind not in KINDS or query.stage not in STAGES:
        raise ValueError('Unknown source type or stage')
    if not all(isinstance(v, str) and v.strip() for v in
               (query.shop, query.scenario, query.session, query.group)):
        raise ValueError('Query needs explicit scope and evaluation group')
    moment(query.at)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5:
        raise ValueError('limit must be between 1 and 5')
    if len({d.id for d in documents}) != len(documents):
        raise ValueError('Duplicate document IDs')
    rejected, eligible = [], []
    for doc in documents:
        reason = exclusion(doc, query)
        if reason:
            rejected.append({'id': doc.id, 'reason': reason})
            continue
        terms = sorted({term for term in doc.search_terms if term.casefold() in query.text.casefold()})
        if not terms:
            rejected.append({'id': doc.id, 'reason': 'no_keyword_match'})
            continue
        eligible.append((doc, terms))
    # Conflicting concurrently applicable knowledge versions are not resolved by rank.
    conflicting_ids = set()
    if query.kind != 'case':
        for doc, _ in eligible:
            versions = {d.version for d, _ in eligible if d.knowledge_key == doc.knowledge_key}
            if len(versions) > 1:
                conflicting_ids.update(d.id for d, _ in eligible if d.knowledge_key == doc.knowledge_key)
    conflict = bool(conflicting_ids)
    hits = []
    if not conflict:
        for doc, terms in sorted(eligible, key=lambda row: (-len(row[1]), row[0].id))[:limit]:
            hits.append({
                'id': doc.id, 'kind': doc.kind, 'version': doc.version,
                'synthetic': doc.synthetic, 'review_status': doc.review,
                'scope': {'shop': doc.shop, 'scenario': doc.scenario, 'stage': doc.stage,
                          'product_id': doc.product_id, 'product_version': doc.product_version},
                'matched_keywords': terms,
                'allowed_use': 'structure_only' if doc.kind == 'case' else 'scoped_reference',
                'reference_points': list(doc.points),
                'forbidden_transfer': list(doc.forbidden_transfer),
                'available_at': doc.available_at,
                'reviewed_at': doc.reviewed_at,
                'evidence_for_review_only': [{'ref': s.ref, 'available_at': s.available_at,
                                              'text': s.text} for s in doc.sources],
            })
    status = 'conflict' if conflict else 'matched' if hits else 'no_match'
    return {'status': status, 'hits': hits, 'rejected': rejected,
            'conflicting_ids': sorted(conflicting_ids),
            'action_status': 'reference_only',
            'notice': {'conflict': '适用资料版本冲突，需人工核实。',
                       'matched': '仅供人工核对；匹配词数量不代表事实正确率。',
                       'no_match': '没有符合条件的资料，不能据此补写政策或客户事实。'}[status]}
