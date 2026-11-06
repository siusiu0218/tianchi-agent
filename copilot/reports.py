"""Explicit staff reports, independent of replies and legacy task records."""
import json
from contextlib import closing
from datetime import datetime, timezone


class ReportStore:
    def __init__(self, store):
        self.store = store
        with closing(store.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS staff_reports (
                    id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL,
                    session TEXT NOT NULL, operator TEXT NOT NULL,
                    reason TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, owner TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS report_events (
                    id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL,
                    operator TEXT NOT NULL, note TEXT NOT NULL,
                    status TEXT NOT NULL, created TEXT NOT NULL);
            ''')

    def submit(self, *, token, session, operator, reason, messages, risk):
        if not all(x.strip() for x in (token, session, operator, reason)) or not messages:
            raise ValueError('请选择要上报的消息，并填写上报人和原因。')
        if any(not isinstance(m.get('message_id'), str) or not m['message_id'] for m in messages):
            raise ValueError('消息缺少可追溯的编号。')
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(dict(messages=messages, risk=risk), ensure_ascii=False)
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM staff_reports WHERE token=?', (token,)).fetchone()
            if existing:
                return existing['id']
            report_id = db.execute('''INSERT INTO staff_reports
                (token,session,operator,reason,payload,status,owner,created,updated)
                VALUES(?,?,?,?,?,'待处理','待主任接手',?,?)''',
                (token, session, operator.strip(), reason.strip(), payload, now, now)).lastrowid
            db.execute('INSERT INTO report_events(report_id,operator,note,status,created) VALUES(?,?,?,?,?)',
                       (report_id, operator.strip(), reason.strip(), '待处理', now))
            return report_id

    def reports(self):
        with closing(self.store.connect()) as db:
            return [dict(row) for row in db.execute('SELECT * FROM staff_reports ORDER BY id DESC')]

    def events(self, report_id):
        with closing(self.store.connect()) as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM report_events WHERE report_id=? ORDER BY id', (report_id,))]

    def update(self, report, *, operator, note, status):
        if not operator.strip() or not note.strip():
            raise ValueError('请填写处理人和处理说明。')
        transitions = {'待处理': ('处理中', '已处理'), '处理中': ('处理中', '已处理'),
                       '已处理': ('处理中',)}
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM staff_reports WHERE id=?', (report['id'],)).fetchone()
            if not row or row['updated'] != report['updated']:
                raise ValueError('上报已被其他操作更新，请刷新后重新打开。')
            if status not in transitions[row['status']]:
                raise ValueError('无效的处理状态。')
            now = datetime.now(timezone.utc).isoformat()
            db.execute('UPDATE staff_reports SET status=?,owner=?,updated=? WHERE id=?',
                       (status, operator.strip(), now, report['id']))
            db.execute('INSERT INTO report_events(report_id,operator,note,status,created) VALUES(?,?,?,?,?)',
                       (report['id'], operator.strip(), note.strip(), status, now))
