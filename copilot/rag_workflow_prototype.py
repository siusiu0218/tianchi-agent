"""EXPERIMENTAL in-memory review workflow. No API, persistence or sending.

Integrates retrieval, reply-context projection and claim audit. Local adoption
requires an explicit human action and remains a draft, not a business operation.
"""
from copy import deepcopy
from dataclasses import asdict

from copilot.rag_claim_prototype import audit
from copilot.rag_prototype import moment
from copilot.rag_reply_prototype import digest, prepare, validate_selection


class ReviewWorkflow:
    def __init__(self, sessions):
        if not sessions:
            raise ValueError('At least one demo session is required')
        self._sessions = deepcopy(sessions)
        if any(key != value['case']['session_id'] for key, value in sessions.items()):
            raise ValueError('Session keys must match case IDs')
        self._active = next(iter(sessions))
        self._revision = 0
        self._generation = 0
        self._pending = None
        self._review = None
        self._status = 'idle'
        self._reason = ''
        self._events = []
        self._history = {key: [] for key in sessions}

    def _snapshot(self):
        state = deepcopy(self._sessions[self._active])
        prepared = prepare(state['case'], state['query'], state['documents'], state['draft'])
        # Current-chat assertions must identify an actual visible current message.
        # Assertion semantics are still manually authored/checked, not inferred.
        messages = {m['message_id']: m for m in state['case']['messages']}
        for source in state['evidence']:
            if source.origin == 'current_chat':
                msg = messages.get(source.id)
                if source.session != self._active or msg is None:
                    raise ValueError('Current evidence does not identify a current message')
                timestamp = msg['发送时间']
                if len(timestamp) == 19:
                    timestamp = timestamp.replace(' ', 'T') + '+08:00'
                if moment(timestamp) != moment(source.available_at):
                    raise ValueError('Evidence and message time mismatch')
        token = digest({'prepared': prepared['context_id'], 'evidence': [asdict(e) for e in state['evidence']],
                        'active': self._active, 'revision': self._revision, 'generation': self._generation})
        return token, state, prepared

    def _invalidate(self, reason):
        self._revision += 1
        self._pending = None
        self._review = None
        self._status, self._reason = 'stale', reason
        self._events.append({'event': 'invalidated', 'session': self._active, 'reason': reason})

    def edit_draft(self, text):
        if not isinstance(text, str):
            raise ValueError('Draft must be text')
        self._history[self._active].append(self._sessions[self._active]['draft'])
        self._sessions[self._active]['draft'] = text
        self._invalidate('draft_changed')

    def switch(self, session):
        if session not in self._sessions:
            raise ValueError('Unknown session')
        self._active = session
        self._invalidate('session_changed')

    def update_sources(self, *, documents=None, evidence=None, case=None, query=None):
        previous = deepcopy(self._sessions[self._active])
        for key, value in [('documents', documents), ('evidence', evidence), ('case', case), ('query', query)]:
            if value is not None:
                self._sessions[self._active][key] = deepcopy(value)
        try:
            self._snapshot()
        except Exception:
            self._sessions[self._active] = previous
            self._invalidate('invalid_source_update')
            raise
        self._invalidate('sources_changed')

    def begin(self, mode='fixed'):
        if mode not in {'fixed', 'annotated'}:
            raise ValueError('Unknown generation mode')
        self._generation += 1
        token, state, prepared = self._snapshot()
        context = deepcopy(prepared['context'])
        context['context_id'] = token
        if mode == 'annotated':
            context.pop('options')
            context.pop('required_ids')
            context['mode'] = 'annotated_sentences_for_human_review'
            context['current_assertions'] = [asdict(e) for e in state['evidence']
                                             if e.origin in {'current_chat', 'current_business'}
                                             and e.session == self._active
                                             and moment(e.available_at) <= moment(state['query'].at)]
        self._pending = {'token': token, 'state': state, 'prepared': prepared, 'context': context, 'mode': mode}
        self._review = None
        self._status, self._reason = 'generating', ''
        return token

    def _still_current(self, token):
        return (self._pending is not None and self._pending['token'] == token
                and self._snapshot()[0] == token)

    def complete(self, token, model):
        if not self._still_current(token):
            return False
        pending = deepcopy(self._pending)
        prepared, state = pending['prepared'], pending['state']
        try:
            response = model(deepcopy(pending['context']))
            if not self._still_current(token):
                return False
            citations = []
            if pending['mode'] == 'fixed':
                validation = deepcopy(prepared)
                validation['context_id'] = token
                reason = validate_selection(response, validation)
                if reason:
                    raise ValueError(reason)
                selected = set(response['segment_ids'])
                options = [o for o in prepared['context']['options'] if o['id'] in selected]
                response = {'context_id': token, 'sentences': [{'text': o['text'], 'claims': []} for o in options]}
                citations = [{'segment': o['id'], 'kind': o['kind'],
                              'sources': [prepared['evidence_map'][ref] for ref in o['refs']]} for o in options]
            checked = audit(response, state['evidence'], session=self._active,
                            cutoff=state['query'].at, context_id=token,
                            draft=state['draft'], risk_level=prepared['risk']['level'])
            if not self._still_current(token):
                return False
        except Exception:
            if self._still_current(token):
                self._pending = None
                self._review = None
                self._status, self._reason = 'error', 'generation_or_audit_failed'
            return False
        self._pending = None
        self._review = {'token': token, 'preview_id': digest({'token': token, 'response': response}),
                        'candidate': deepcopy(response), 'audit': checked,
                        'segment_citations': citations, 'mode': pending['mode']}
        self._status = checked['status']
        self._reason = 'findings_block_adoption' if checked['status'] == 'blocked' else 'human_review_required'
        self._events.append({'event': 'checked', 'session': self._active, 'status': self._status})
        return True

    def adopt(self, preview_id, *, actor, note):
        if (self._status != 'needs_human_review' or self._review is None
                or preview_id != self._review['preview_id'] or not actor.strip() or not note.strip()):
            return False
        if self._snapshot()[0] != self._review['token']:
            self._invalidate('snapshot_changed_before_adoption')
            return False
        old = self._sessions[self._active]['draft']
        self._history[self._active].append(old)
        self._sessions[self._active]['draft'] = self._review['audit']['suggestion']
        self._events.append({'event': 'adopted_local_draft', 'session': self._active,
                             'preview_id': preview_id, 'actor': actor, 'note': note})
        self._revision += 1
        self._status, self._reason = 'adopted_local_draft', 'not_sent'
        return True

    def reject(self):
        self._invalidate('human_rejected')
        self._status = 'rejected'

    def view(self):
        _, state, prepared = self._snapshot()
        return deepcopy({'session': self._active, 'sessions': list(self._sessions),
                         'cutoff': state['query'].at, 'case_snapshot': state['case'],
                         'status': self._status, 'reason': self._reason, 'draft': state['draft'],
                         'draft_history': self._history[self._active], 'risk': prepared['risk'],
                         'messages': state['case']['messages'], 'retrieval': prepared['retrieval'],
                         'evidence': [asdict(e) for e in state['evidence']], 'review': self._review,
                         'events': self._events, 'business_actions': [], 'persistence': 'memory_only'})
