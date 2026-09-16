"""Local review ledger. No customer messages or external tickets are sent."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

TRANSITIONS = {
    "待处理": ("待处理", "处理中"),
    "处理中": ("处理中", "已解决"),
    "已解决": ("已解决", "处理中", "已关闭"),
    "已关闭": ("已关闭", "处理中"),
}


def overdue(task, hours=24, now=None):
    """Demo threshold from local task creation, not historical chat timestamps."""
    now = now or datetime.now(timezone.utc)
    return (task["status"] in {"待处理", "处理中"}
            and (now - datetime.fromisoformat(task["created"])).total_seconds() > hours * 3600)


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL,
                    session TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    session TEXT PRIMARY KEY, review_id INTEGER NOT NULL,
                    owner TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL,
                    created TEXT NOT NULL, operator TEXT NOT NULL, reason TEXT NOT NULL,
                    before_state TEXT NOT NULL, after_state TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save(self, *, session, cutoff, original, edited, source, risk,
             decision, operator, owner, reason, confirmed):
        if not confirmed:
            raise ValueError("请先勾选确认本次操作。")
        if decision not in {"采纳", "修改后确认", "驳回"}:
            raise ValueError("无效的审核操作。")
        if not operator.strip() or not reason.strip():
            raise ValueError("请填写操作人和审核原因。")
        if decision != "驳回" and (not owner.strip() or not edited.strip()):
            raise ValueError("确认前请填写负责人和回复内容。")
        if decision == "采纳" and edited != original:
            raise ValueError("内容已修改，请选择“修改后确认”。")
        payload = dict(cutoff=cutoff, original=original, edited=edited, source=source,
                       risk=risk, decision=decision, operator=operator.strip(),
                       owner=owner.strip(), reason=reason.strip())
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        token = hashlib.sha256((session + encoded).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM reviews WHERE token=?", (token,)).fetchone()
            if existing:
                return existing["id"], False
            before = db.execute("SELECT * FROM tasks WHERE session=?", (session,)).fetchone()
            if before and before["status"] in {"已解决", "已关闭"} and decision != "驳回":
                raise ValueError("任务已解决或关闭，请先在主管看板重新打开，再保存新的确认。")
            cursor = db.execute(
                "INSERT INTO reviews(token,session,created,payload) VALUES(?,?,?,?)",
                (token, session, now, encoded))
            review_id = cursor.lastrowid
            if decision != "驳回":
                db.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?)
                    ON CONFLICT(session) DO UPDATE SET review_id=excluded.review_id,
                    owner=excluded.owner, updated=excluded.updated""",
                    (session, review_id, owner.strip(), "待处理", now, now))
                after = dict(db.execute("SELECT * FROM tasks WHERE session=?", (session,)).fetchone())
                self._event(db, session, now, operator.strip(), f"审核 #{review_id}：{reason.strip()}",
                            dict(before) if before else {}, after)
            return review_id, True

    @staticmethod
    def _event(db, session, now, operator, reason, before, after):
        db.execute("INSERT INTO task_events(session,created,operator,reason,before_state,after_state) VALUES(?,?,?,?,?,?)",
                   (session, now, operator, reason, json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False)))

    def tasks(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT tasks.*, reviews.payload FROM tasks JOIN reviews ON reviews.id=tasks.review_id ORDER BY tasks.created DESC")]

    def events(self, session):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM task_events WHERE session=? ORDER BY id", (session,))]

    def update_task(self, session, *, expected_updated, owner, status, operator, reason, confirmed):
        if not confirmed or not all(x.strip() for x in (owner, operator, reason)):
            raise ValueError("请填写负责人、操作人、处理说明，并勾选确认。")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE session=?", (session,)).fetchone()
            if not row:
                raise ValueError("任务不存在，请刷新看板。")
            before = dict(row)
            if row["updated"] != expected_updated:
                raise ValueError("任务已被其他操作更新，请刷新看板后重新核对。")
            if status not in TRANSITIONS[row["status"]]:
                raise ValueError("状态不能跳步：请按待处理、处理中、已解决、已关闭的顺序推进。")
            if owner.strip() == row["owner"] and status == row["status"]:
                return False
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE tasks SET owner=?,status=?,updated=? WHERE session=?",
                       (owner.strip(), status, now, session))
            after = dict(before, owner=owner.strip(), status=status, updated=now)
            self._event(db, session, now, operator.strip(), reason.strip(), before, after)
            return True

    def history(self, session):
        with closing(self.connect()) as db:
            return [dict(id=row["id"], created=row["created"], **json.loads(row["payload"]))
                    for row in db.execute(
                        "SELECT * FROM reviews WHERE session=? ORDER BY id DESC", (session,))]

    def task(self, session):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM tasks WHERE session=?", (session,)).fetchone()
            return dict(row) if row else None
