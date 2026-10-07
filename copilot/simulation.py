"""Isolated customer messages plus existing local staff replies, in UTC order."""
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4


class SimulationProvider:
    includes_local_replies = True

    def __init__(self, store):
        self.store = store
        self.source = store.path
        self.frames = {}  # No fabricated orders or tickets in a blank test.
        with closing(store.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS test_customer_messages (
                id TEXT PRIMARY KEY, session TEXT NOT NULL,
                created TEXT NOT NULL, content TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS test_ai_messages (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, reply_to TEXT UNIQUE NOT NULL,
                created TEXT NOT NULL, content TEXT NOT NULL)''')

    def append_reply(self, session, content, expected_messages):
        """Store an automatic test reply without recording a human approval."""
        if not content.strip() or not expected_messages or expected_messages[-1]['角色'] != '买家':
            raise ValueError('当前没有等待回复的客户消息。')
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if self.messages(session) != expected_messages:
                raise ValueError('聊天记录已变化，未采用旧回复，请重试。')
            db.execute('INSERT INTO test_ai_messages VALUES (?, ?, ?, ?, ?)',
                       ('AI-' + uuid4().hex, session, expected_messages[-1]['message_id'],
                        datetime.now(timezone.utc).isoformat(), content.strip()))

    def sessions(self):
        with closing(self.store.connect()) as db:
            return [row[0] for row in db.execute(
                "SELECT session FROM test_customer_messages UNION SELECT session FROM composer_drafts "
                "WHERE scope='simulation-customer' ORDER BY session")]

    def append_customer(self, session, content):
        content = content.strip()
        if not content:
            raise ValueError('请先输入客户消息。')
        if len(content) > 4000:
            raise ValueError('单条测试消息请控制在 4000 字以内。')
        message_id = 'TEST-' + uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        with closing(self.store.connect()) as db, db:
            db.execute('INSERT INTO test_customer_messages VALUES (?, ?, ?, ?)',
                       (message_id, session, created, content))
        return message_id

    def messages(self, session):
        with closing(self.store.connect()) as db:
            customers = list(db.execute(
                'SELECT id, created, content FROM test_customer_messages WHERE session=? ORDER BY created',
                (session,)))
        rows = [(created, mid, '买家', content) for mid, created, content in customers]
        with closing(self.store.connect()) as db:
            rows.extend((r['created'], r['id'], '客服', r['content']) for r in db.execute(
                'SELECT * FROM test_ai_messages WHERE session=? ORDER BY created', (session,)))
        rows.extend((r['created'], f"LOCAL-{r['id']}", '客服', r['content'])
                    for r in self.store.simulated_messages(session))
        return [dict(message_id=mid, 发送时间=datetime.fromisoformat(created).astimezone(timezone.utc)
                     .replace(tzinfo=None).isoformat(sep=' ', timespec='microseconds'),
                     角色=role, message_text=content, 内容类型='文字', image_path='')
                for created, mid, role, content in sorted(rows, key=lambda r: datetime.fromisoformat(r[0]))]

    def get_case(self, session_id, cutoff=None):
        messages = self.messages(session_id)
        if not messages:
            raise ValueError('请先发送一条模拟客户消息。')
        cutoff = cutoff or messages[-1]['发送时间']
        return dict(session_id=session_id, cutoff=cutoff,
                    messages=[m for m in messages if m['发送时间'] <= cutoff],
                    orders=[], tickets=[], image_notice='模拟测试未提供图片，不能确认图片内容。',
                    time_notice='本地模拟对话，时间为 UTC；未连接客户渠道，未提供订单或工单凭证。')

    def ticket_snapshot(self, session):
        return []

    def logistics_snapshot(self, session):
        return {'original': [], 'replacement': []}
