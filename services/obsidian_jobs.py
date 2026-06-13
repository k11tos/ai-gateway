import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_COMMANDS = {"ask", "ingest", "capture", "draft", "status"}
FINAL_STATUSES = {"succeeded", "failed"}
ALL_STATUSES = {"queued", "running", "succeeded", "failed", "expired"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObsidianJobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS obsidian_jobs (
                    id text primary key,
                    command text not null,
                    payload_json text not null,
                    status text not null,
                    telegram_chat_id integer nullable,
                    telegram_message_id integer nullable,
                    requested_by integer nullable,
                    result_text text nullable,
                    error_text text nullable,
                    created_at text not null,
                    locked_at text nullable,
                    finished_at text nullable
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_jobs_queue "
                "ON obsidian_jobs(status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_jobs_finished "
                "ON obsidian_jobs(finished_at)"
            )

    def create_job(
        self,
        *,
        command: str,
        payload: dict[str, Any],
        telegram_chat_id: int | None,
        telegram_message_id: int | None,
        requested_by: int | None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        created_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO obsidian_jobs (
                    id, command, payload_json, status, telegram_chat_id,
                    telegram_message_id, requested_by, created_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    command,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    telegram_chat_id,
                    telegram_message_id,
                    requested_by,
                    created_at,
                ),
            )
        return {"job_id": job_id, "status": "queued"}

    def claim_next_job(self) -> dict[str, Any] | None:
        locked_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM obsidian_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None

            conn.execute(
                "UPDATE obsidian_jobs SET status = 'running', locked_at = ? WHERE id = ?",
                (locked_at, row["id"]),
            )
            conn.execute("COMMIT")

        return self.get_job(row["id"])

    def complete_job(
        self,
        job_id: str,
        *,
        status: str,
        result_text: str | None,
        error_text: str | None,
    ) -> dict[str, Any] | None:
        finished_at = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE obsidian_jobs
                SET status = ?, result_text = ?, error_text = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, result_text, error_text, finished_at, job_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM obsidian_jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_job(row) if row else None

    def status_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM obsidian_jobs GROUP BY status"
            ).fetchall()
            last = conn.execute(
                """
                SELECT id, command, status, finished_at, error_text
                FROM obsidian_jobs
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchone()
        counts = {status: 0 for status in ALL_STATUSES}
        counts.update({row["status"]: row["count"] for row in rows})
        return {"queue_counts": counts, "last_finished_job": dict(last) if last else None}


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "command": row["command"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "telegram_chat_id": row["telegram_chat_id"],
        "telegram_message_id": row["telegram_message_id"],
        "requested_by": row["requested_by"],
        "result_text": row["result_text"],
        "error_text": row["error_text"],
        "created_at": row["created_at"],
        "locked_at": row["locked_at"],
        "finished_at": row["finished_at"],
    }
