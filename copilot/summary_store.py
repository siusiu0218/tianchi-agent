"""Versioned local summaries, corrections and directed, topic-scoped links."""
import copy
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


class SummaryStore:
    def __init__(self, path, namespace):
        self.path, self.namespace = path, namespace
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS handover_versions (
                    id INTEGER PRIMARY KEY, scope TEXT, session TEXT, created TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS handover_edits (
                    id INTEGER PRIMARY KEY, scope TEXT, session TEXT, item TEXT, created TEXT,
                    actor TEXT, reason TEXT, original TEXT, edited TEXT, source_hash TEXT);
                CREATE TABLE IF NOT EXISTS handover_links (
                    scope TEXT, session TEXT, other TEXT, topic TEXT, active INTEGER,
                    PRIMARY KEY(scope,session,other,topic));
                CREATE TABLE IF NOT EXISTS handover_link_events (
                    id INTEGER PRIMARY KEY, scope TEXT, session TEXT, other TEXT, topic TEXT,
                    active INTEGER, actor TEXT, created TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def latest(self, session):
        with closing(self.connect()) as db:
            row = db.execute('SELECT body FROM handover_versions WHERE scope=? AND session=? ORDER BY id DESC LIMIT 1', (self.namespace, session)).fetchone()
        return json.loads(row['body']) if row else None

    def save(self, session, summary):
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO handover_versions(scope,session,created,body) VALUES(?,?,?,?)',
                       (self.namespace, session, self.now(), json.dumps(summary, ensure_ascii=False)))

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def history(self, session):
        with closing(self.connect()) as db:
            return [dict(r) for r in db.execute('SELECT * FROM handover_edits WHERE scope=? AND session=? ORDER BY id', (self.namespace, session))]

    def correct(self, session, item, value, actor, reason):
        if not all(x.strip() for x in (value, actor, reason)):
            raise ValueError('请填写纠正内容、操作人和修改说明。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT id FROM handover_edits WHERE scope=? AND session=? AND item=? ORDER BY id DESC LIMIT 1',
                                (self.namespace, session, item['id'])).fetchone()
            expected = item.get('correction', {}).get('id')
            if (latest['id'] if latest else None) != expected:
                raise ValueError('此项已被其他操作纠正，请重新打开摘要后再修改。')
            db.execute('INSERT INTO handover_edits(scope,session,item,created,actor,reason,original,edited,source_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                       (self.namespace, session, item['id'], self.now(), actor.strip(), reason.strip(), item['text'], value.strip(), item['source_hash']))

    def correct_many(self, session, changes, actor, reason):
        """Apply one review of several handover items as a single transaction."""
        if not changes or not actor.strip() or not reason.strip() or any(not value.strip() for _, value in changes):
            raise ValueError('请填写修改内容、操作人和修改说明。')
        if len({item['id'] for item, _ in changes}) != len(changes):
            raise ValueError('同一事项不能重复修改。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for item, value in changes:
                latest = db.execute('SELECT id FROM handover_edits WHERE scope=? AND session=? AND item=? ORDER BY id DESC LIMIT 1',
                                    (self.namespace, session, item['id'])).fetchone()
                expected = item.get('correction', {}).get('id')
                if (latest['id'] if latest else None) != expected:
                    raise ValueError('接手要点已被修改，请重新打开后再保存。')
            for item, value in changes:
                db.execute('INSERT INTO handover_edits(scope,session,item,created,actor,reason,original,edited,source_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                           (self.namespace, session, item['id'], self.now(), actor.strip(), reason.strip(), item['text'], value.strip(), item['source_hash']))

    def apply(self, session, summary):
        result = copy.deepcopy(summary)
        edits = {r['item']: r for r in self.history(session)}
        present = set()
        for item in result['items']:
            present.add(item['id'])
            if item['id'] in edits:
                edit = edits[item['id']]
                item['generated'] = item['text']
                item['text'] = edit['edited']
                item['correction'] = edit
                item['conflict'] = item['source_hash'] != edit['source_hash']
        result['orphaned_edits'] = [r for k, r in edits.items() if k not in present]
        return result

    def links(self, session):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT other,topic FROM handover_links WHERE scope=? AND session=? AND active=1', (self.namespace, session)).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row['other'], []).append(row['topic'])
        return result

    def set_link(self, session, other, topic, active, actor):
        if not actor.strip() or session == other:
            raise ValueError('请填写操作人，且不能关联自身。')
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO handover_links VALUES(?,?,?,?,?) ON CONFLICT(scope,session,other,topic) DO UPDATE SET active=excluded.active',
                       (self.namespace, session, other, topic, int(active)))
            db.execute('INSERT INTO handover_link_events(scope,session,other,topic,active,actor,created) VALUES(?,?,?,?,?,?,?)',
                       (self.namespace, session, other, topic, int(active), actor.strip(), self.now()))
