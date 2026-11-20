from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any


class MASState:
    def __init__(self, path: str = "logs/mas.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, role TEXT NOT NULL, pilot TEXT NOT NULL,
                objective TEXT NOT NULL, status TEXT NOT NULL,
                payload TEXT, result TEXT, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, pilot TEXT NOT NULL,
                source TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                idempotency_key TEXT PRIMARY KEY, pilot TEXT NOT NULL,
                mcp_tool TEXT NOT NULL, action TEXT NOT NULL,
                arguments TEXT NOT NULL, outcome TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def create_task(self, role: str, pilot: str, objective: str, payload: dict[str, Any] | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO tasks(id,role,pilot,objective,status,payload,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (task_id, role, pilot, objective, "submitted",
             __import__("json").dumps(payload or {}), now, now),
        )
        self.db.commit()
        return task_id

    def update_task(self, task_id: str, status: str, result: dict[str, Any] | None = None,
                    error: str | None = None) -> None:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self.db.execute(
            "UPDATE tasks SET status=?,result=?,error=?,updated_at=? WHERE id=?",
            (status,
             __import__("json").dumps(result) if result is not None else None,
             error, now, task_id),
        )
        self.db.commit()

    def record_observation(self, pilot: str, source: str, payload: Any) -> None:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO observations(pilot,source,payload,created_at) VALUES(?,?,?,?)",
            (pilot, source, __import__("json").dumps(payload, default=str), now),
        )
        self.db.commit()

    def action_is_completed(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT outcome,status FROM actions WHERE idempotency_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        if row["status"] == "completed":
            return __import__("json").loads(row["outcome"]) if row["outcome"] else {"status": "completed"}
        return None

    def start_action(self, key: str, pilot: str, tool: str, action: str, arguments: dict[str, Any]) -> bool:
        if self.action_is_completed(key):
            return False
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        try:
            self.db.execute(
                "INSERT INTO actions(idempotency_key,pilot,mcp_tool,action,arguments,status,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (key, pilot, tool, action, __import__("json").dumps(arguments),
                 "started", now),
            )
            self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def complete_action(self, key: str, outcome: Any) -> None:
        self.db.execute(
            "UPDATE actions SET outcome=?,status='completed' WHERE idempotency_key=?",
            (__import__("json").dumps(outcome, default=str), key),
        )
        self.db.commit()

    def pending_tasks(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id,role,pilot,objective,payload FROM tasks "
            "WHERE status IN ('submitted','working') ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]
