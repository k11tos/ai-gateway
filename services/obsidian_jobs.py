import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ALLOWED_COMMANDS = {"ask", "ingest", "draft", "lint", "save", "status", "update"}
FINAL_STATUSES = {"succeeded", "failed"}
ALL_STATUSES = {"queued", "running", "succeeded", "failed", "expired"}
TRUNCATION_MARKER = "...[truncated by ai-gateway]"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None or max_chars < 0 or len(value) <= max_chars:
        return value
    if max_chars <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:max_chars]
    return f"{value[: max_chars - len(TRUNCATION_MARKER)]}{TRUNCATION_MARKER}"


class JobTransitionConflict(Exception):
    pass


class JobNotificationConflict(Exception):
    pass


class ObsidianJobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.result_retention_hours = _read_int_env(
            "OBSIDIAN_JOB_RESULT_RETENTION_HOURS", 24
        )
        self.error_retention_hours = _read_int_env(
            "OBSIDIAN_JOB_ERROR_RETENTION_HOURS", 72
        )
        self.max_result_chars = _read_int_env("OBSIDIAN_JOB_MAX_RESULT_CHARS", 20000)
        self.max_error_chars = _read_int_env("OBSIDIAN_JOB_MAX_ERROR_CHARS", 4000)
        self.notification_lease_seconds = _read_int_env(
            "OBSIDIAN_JOB_NOTIFICATION_LEASE_SECONDS", 300
        )
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
            conn.execute("""
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
                    finished_at text nullable,
                    result_notified_at text nullable,
                    result_notification_claimed_until text nullable
                )
                """)
            self._ensure_column(
                conn, "obsidian_jobs", "result_notified_at", "text nullable"
            )
            self._ensure_column(
                conn,
                "obsidian_jobs",
                "result_notification_claimed_until",
                "text nullable",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_jobs_queue "
                "ON obsidian_jobs(status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_jobs_finished "
                "ON obsidian_jobs(finished_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_jobs_notifications "
                "ON obsidian_jobs("
                "result_notified_at, result_notification_claimed_until, "
                "status, telegram_chat_id, finished_at)"
            )

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_job(
        self,
        *,
        command: str,
        payload: dict[str, Any],
        telegram_chat_id: int | None,
        telegram_message_id: int | None,
        requested_by: int | None,
    ) -> dict[str, Any]:
        self.cleanup_obsidian_job_payloads()
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
            row = conn.execute("""
                SELECT * FROM obsidian_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """).fetchone()
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
        result_text = _truncate_text(result_text, self.max_result_chars)
        error_text = _truncate_text(error_text, self.max_error_chars)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE obsidian_jobs
                SET status = ?,
                    result_text = ?,
                    error_text = ?,
                    finished_at = ?,
                    result_notified_at = NULL,
                    result_notification_claimed_until = NULL
                WHERE id = ? AND status = 'running'
                """,
                (status, result_text, error_text, finished_at, job_id),
            )
            if cursor.rowcount == 0:
                existing = conn.execute(
                    "SELECT * FROM obsidian_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if existing is None:
                    return None
                raise JobTransitionConflict(
                    f"job {job_id} cannot transition from {existing['status']} to {status}"
                )
        return self.get_job(job_id)

    def cleanup_obsidian_job_payloads(
        self, now: datetime | None = None
    ) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        result_cutoff = (now - timedelta(hours=self.result_retention_hours)).isoformat()
        error_cutoff = (now - timedelta(hours=self.error_retention_hours)).isoformat()
        with self._connect() as conn:
            result_cursor = conn.execute(
                """
                UPDATE obsidian_jobs
                SET result_text = NULL
                WHERE status = 'succeeded'
                  AND result_text IS NOT NULL
                  AND finished_at IS NOT NULL
                  AND finished_at < ?
                """,
                (result_cutoff,),
            )
            error_cursor = conn.execute(
                """
                UPDATE obsidian_jobs
                SET error_text = NULL
                WHERE status = 'failed'
                  AND error_text IS NOT NULL
                  AND finished_at IS NOT NULL
                  AND finished_at < ?
                """,
                (error_cutoff,),
            )
        return {
            "result_text_cleared": result_cursor.rowcount,
            "error_text_cleared": error_cursor.rowcount,
        }

    def claim_next_unnotified_job(self) -> dict[str, Any] | None:
        self.cleanup_obsidian_job_payloads()
        now = utc_now_iso()
        claimed_until = (
            datetime.now(timezone.utc)
            + timedelta(seconds=self.notification_lease_seconds)
        ).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM obsidian_jobs
                WHERE status IN ('succeeded', 'failed')
                  AND result_notified_at IS NULL
                  AND telegram_chat_id IS NOT NULL
                  AND (
                    result_notification_claimed_until IS NULL
                    OR result_notification_claimed_until <= ?
                  )
                ORDER BY finished_at ASC, created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None

            conn.execute(
                """
                UPDATE obsidian_jobs
                SET result_notification_claimed_until = ?
                WHERE id = ?
                """,
                (claimed_until, row["id"]),
            )
            conn.execute("COMMIT")
        return self.get_job(row["id"])

    def mark_job_notified(self, job_id: str) -> dict[str, Any] | None:
        notified_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM obsidian_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if existing is None:
                conn.execute("COMMIT")
                return None
            if (
                existing["status"] not in FINAL_STATUSES
                or existing["telegram_chat_id"] is None
            ):
                conn.execute("COMMIT")
                raise JobNotificationConflict(
                    f"job {job_id} is not completed and deliverable"
                )

            conn.execute(
                """
                UPDATE obsidian_jobs
                SET result_notified_at = COALESCE(result_notified_at, ?),
                    result_notification_claimed_until = NULL
                WHERE id = ?
                """,
                (notified_at, job_id),
            )
            conn.execute("COMMIT")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM obsidian_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return row_to_job(row) if row else None

    def status_summary(self) -> dict[str, Any]:
        cleanup_counts = self.cleanup_obsidian_job_payloads()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM obsidian_jobs GROUP BY status"
            ).fetchall()
            last = conn.execute("""
                SELECT id, command, status, finished_at, error_text
                FROM obsidian_jobs
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
                """).fetchone()
        counts = {status: 0 for status in ALL_STATUSES}
        counts.update({row["status"]: row["count"] for row in rows})
        return {
            "queue_counts": counts,
            "last_finished_job": dict(last) if last else None,
            "payload_cleanup": cleanup_counts,
        }


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
        "result_notified_at": row["result_notified_at"],
        "result_notification_claimed_until": row["result_notification_claimed_until"],
    }
