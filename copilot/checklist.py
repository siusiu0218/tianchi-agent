"""Local, human-controlled follow-up checklist for a conversation."""
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image


def suggestions(summary):
    """Turn evidence-bound pending summary items into small, checkable actions."""
    result = []
    for item in summary['items']:
        if item['field'] != '待解决' or '现有记录未显示新增待办' in item['text']:
            continue
        topic, body = item['topic'], item['text']
        if topic == '商品与换货':
            actions = [('发出', '确认补发是否实际发出'), ('签收', '确认客户是否收到补发商品且商品完好')]
            if '寄回' in body or '退回' in body:
                actions.append(('寄回', '确认旧商品寄回安排是否落实'))
        elif topic == '图片资料':
            actions = [('图片', '核实客户所发图片内容（当前图片文件不可读）')]
        elif item.get('authored'):
            # Only a model item supported by newly changed source evidence can
            # add detail beside an existing local task for the same topic.
            actions = [('事项:ai:' + item['source_hash'][:12], body)]
        elif topic == '使用不适':
            actions = [('不适', '核实消费者报告的不适及后续处理情况')]
        elif topic == '退款与费用':
            actions = [('费用', '核实退款或费用处理结果')]
        elif topic == '回访跟进':
            actions = [('回访', '核实回访是否落实')]
        else:
            actions = [('事项', body if len(body) <= 90 else '核实' + topic + '的处理结果')]
        for suffix, text in actions:
            result.append({'source_key': item['id'] + ':' + suffix, 'source_hash': item['source_hash'],
                           'text': text, 'refs': item['refs']})
    return result


class ChecklistStore:
    def __init__(self, path, namespace):
        self.path, self.namespace = Path(path), namespace
        self.files = self.path.parent / (self.path.stem + '-checklist-files')
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS checklist_items (
                    id INTEGER PRIMARY KEY, scope TEXT NOT NULL, session TEXT NOT NULL,
                    source_key TEXT, source_hash TEXT, text TEXT NOT NULL,
                    refs TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                    completion_ref TEXT NOT NULL DEFAULT '',
                    deleted INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL,
                    actor TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checklist_events (
                    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, action TEXT NOT NULL,
                    actor TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checklist_files (
                    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, filename TEXT NOT NULL,
                    original_name TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS checklist_lookup ON checklist_items(scope,session,id);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def _owned(self, db, item_id):
        row = db.execute('SELECT * FROM checklist_items WHERE id=? AND scope=?',
                         (item_id, self.namespace)).fetchone()
        if not row or row['deleted']:
            raise ValueError('清单事项已不存在，请刷新后重试。')
        return row

    def items(self, session, include_deleted=False):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM checklist_items WHERE scope=? AND session=?'
                              + ('' if include_deleted else ' AND deleted=0') + ' ORDER BY id',
                              (self.namespace, session)).fetchall()
            return [{**dict(row), 'refs': json.loads(row['refs']),
                     'files': [dict(f) for f in db.execute('SELECT * FROM checklist_files WHERE item_id=? ORDER BY id',
                                                           (row['id'],))],
                     'completion_event': dict(event) if (event := db.execute(
                         "SELECT actor,created FROM checklist_events WHERE item_id=? AND action='完成' ORDER BY id DESC LIMIT 1",
                         (row['id'],)).fetchone()) and row['done'] else None} for row in rows]

    def sync(self, session, proposed, retire_stale=False):
        """Sync suggestions while preserving every human-touched checklist item."""
        added = 0
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if retire_stale:
                current_keys = {item['source_key'] for item in proposed}
                stale = db.execute('''SELECT id,source_key,text FROM checklist_items
                    WHERE scope=? AND session=? AND deleted=0 AND origin='摘要建议'
                    AND done=0 AND NOT EXISTS
                    (SELECT 1 FROM checklist_events WHERE item_id=checklist_items.id)
                    AND NOT EXISTS
                    (SELECT 1 FROM checklist_files WHERE item_id=checklist_items.id)''',
                    (self.namespace, session)).fetchall()
                for row in stale:
                    if row['source_key'] in current_keys:
                        continue
                    now = self.now()
                    db.execute('UPDATE checklist_items SET deleted=1,updated=? WHERE id=?',
                               (now, row['id']))
                    db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                               (row['id'], '建议撤回', '系统', row['text'], now))
            prior = db.execute('SELECT source_key,source_hash,text,deleted FROM checklist_items WHERE scope=? AND session=?',
                               (self.namespace, session)).fetchall()
            for item in proposed:
                key, source_hash = item['source_key'], item['source_hash']
                if any(r['source_key'] == key and (not r['deleted'] or r['source_hash'] == source_hash)
                       for r in prior):
                    continue
                base_key = key.split(':事项:ai:')[0]
                if ':事项:ai:' in key and any((r['source_key'] or '').startswith(base_key + ':')
                                         and r['source_hash'] == source_hash for r in prior):
                    continue
                # An AI rephrase must not recreate an existing or dismissed task.
                if any(r['text'].strip() == item['text'].strip() and (not r['deleted'] or r['source_hash'] == source_hash)
                       for r in prior):
                    continue
                now = self.now()
                db.execute('''INSERT INTO checklist_items
                    (scope,session,source_key,source_hash,text,refs,origin,actor,created,updated)
                    VALUES(?,?,?,?,?,?,'摘要建议','系统',?,?)''',
                    (self.namespace, session, key, source_hash, item['text'],
                     json.dumps(item['refs'], ensure_ascii=False), now, now))
                prior = [*prior, dict(source_key=key, source_hash=source_hash, text=item['text'], deleted=0)]
                added += 1
        return added

    def add(self, session, text, actor, refs=()):
        if not text.strip() or not actor.strip():
            raise ValueError('请填写事项和操作人。')
        now = self.now()
        with closing(self.connect()) as db, db:
            item_id = db.execute('''INSERT INTO checklist_items
                (scope,session,source_key,source_hash,text,refs,origin,actor,created,updated)
                VALUES(?,?,NULL,NULL,?,?,'人工添加',?,?,?)''',
                (self.namespace, session, text.strip(), json.dumps(list(refs), ensure_ascii=False),
                 actor.strip(), now, now)).lastrowid
            db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                       (item_id, '添加', actor.strip(), text.strip(), now))
        return item_id

    def edit(self, item_id, text, actor, refs=None):
        if not text.strip() or not actor.strip():
            raise ValueError('请填写事项和操作人。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._owned(db, item_id)
            now = self.now()
            new_refs = json.dumps(list(refs), ensure_ascii=False) if refs is not None else row['refs']
            changed = text.strip() != row['text'] or new_refs != row['refs']
            db.execute('UPDATE checklist_items SET text=?,refs=?,done=?,completion_ref=?,updated=? WHERE id=?',
                       (text.strip(), new_refs, 0 if changed else row['done'],
                        '' if changed else row['completion_ref'], now, item_id))
            db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                       (item_id, '修改', actor.strip(), row['text'] + ' → ' + text.strip(), now))
            if changed and row['done']:
                db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                           (item_id, '重新待办', actor.strip(), '事项修改后须重新核实。', now))

    def delete(self, item_id, actor):
        if not actor.strip():
            raise ValueError('请填写操作人。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._owned(db, item_id)
            now = self.now()
            db.execute('UPDATE checklist_items SET deleted=1,updated=? WHERE id=?', (now, item_id))
            db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                       (item_id, '删除', actor.strip(), row['text'], now))

    def set_done(self, item_id, done, actor, completion_ref=''):
        if not actor.strip():
            raise ValueError('请填写操作人。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._owned(db, item_id)
            if done and not completion_ref and not db.execute(
                    'SELECT 1 FROM checklist_files WHERE item_id=? LIMIT 1', (item_id,)).fetchone():
                raise ValueError('请先为此事项选择记录依据或附上截图。')
            if bool(row['done']) == bool(done):
                return
            now = self.now()
            db.execute('UPDATE checklist_items SET done=?,completion_ref=?,updated=? WHERE id=?',
                       (int(done), completion_ref if done else '', now, item_id))
            db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                       (item_id, '完成' if done else '重新待办', actor.strip(),
                        row['text'] + (' · 依据：' + completion_ref if done and completion_ref else ''), now))

    def attach(self, item_id, source, actor):
        if not actor.strip():
            raise ValueError('请填写操作人。')
        source = Path(source)
        if not source.is_file() or source.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('请选择不超过 10 MB 的图片文件。')
        try:
            with Image.open(source) as image:
                kind = image.format
                image.verify()
        except (OSError, ValueError) as exc:
            raise ValueError('所选文件不是可读取的截图。') from exc
        suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}.get(kind)
        if not suffix:
            raise ValueError('截图仅支持 PNG、JPEG 或 WebP。')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._owned(db, item_id)
            folder = self.files / hashlib.sha256(self.namespace.encode()).hexdigest() / str(item_id)
            folder.mkdir(parents=True, exist_ok=True)
            filename = uuid4().hex + suffix
            destination = folder / filename
            shutil.copyfile(source, destination)
            now = self.now()
            try:
                db.execute('INSERT INTO checklist_files(item_id,filename,original_name,actor,created) VALUES(?,?,?,?,?)',
                           (item_id, str(destination.relative_to(self.files)), source.name, actor.strip(), now))
                db.execute('INSERT INTO checklist_events(item_id,action,actor,detail,created) VALUES(?,?,?,?,?)',
                           (item_id, '附截图', actor.strip(), source.name, now))
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def screenshot_path(self, file_row):
        candidate = (self.files / file_row['filename']).resolve()
        if self.files.resolve() not in candidate.parents:
            raise ValueError('截图路径无效。')
        return candidate

    def events(self, item_id):
        with closing(self.connect()) as db:
            if not db.execute('SELECT 1 FROM checklist_items WHERE id=? AND scope=?',
                              (item_id, self.namespace)).fetchone():
                raise ValueError('清单事项不存在。')
            return [dict(row) for row in db.execute('SELECT * FROM checklist_events WHERE item_id=? ORDER BY id',
                                                   (item_id,))]
