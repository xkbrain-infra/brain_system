#!/usr/bin/env python3
"""IPC Reliability - Message state tracking with timeout/retry support.

Provides persistent message state storage and retry logic for IPC messages.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("ipc_reliability")

DEFAULT_DB_PATH = "/xkagent_infra/runtime/data/ipc_state.db"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 10
DEFAULT_RETRY_WINDOW_SECONDS = 300


class MessageStatus(Enum):
    SENT = "sent"
    ACKED = "acked"
    TIMEOUT = "timeout"
    RETRIED = "retried"
    FAILED = "failed"


@dataclass
class MessageState:
    message_id: str
    target: str
    status: MessageStatus
    payload: str
    sent_at: float
    deadline_at: float
    attempt_count: int
    last_retry_at: float | None
    conversation_id: str | None
    message_type: str
    from_agent: str
    created_at: float
    updated_at: float


class MessageStateStore:
    """SQLite-backed message state store for IPC reliability tracking."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        retry_window_seconds: float = DEFAULT_RETRY_WINDOW_SECONDS,
    ) -> None:
        self.db_path = db_path
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.retry_window_seconds = retry_window_seconds
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ipc_messages (
                message_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'sent',
                payload TEXT,
                sent_at REAL NOT NULL,
                deadline_at REAL NOT NULL,
                attempt_count INTEGER DEFAULT 1,
                last_retry_at REAL,
                conversation_id TEXT,
                message_type TEXT DEFAULT 'request',
                from_agent TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ipc_status_deadline
            ON ipc_messages(status, deadline_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ipc_target
            ON ipc_messages(target)
        """)
        conn.commit()
        logger.info("IPC state store initialized: %s", self.db_path)

    def generate_message_id(self) -> str:
        return str(uuid.uuid4())

    def record_send(
        self,
        message_id: str,
        from_agent: str,
        target: str,
        payload: str,
        message_type: str = "request",
        conversation_id: str | None = None,
        timeout_override: float | None = None,
    ) -> MessageState:
        """Record a new message send with timeout tracking."""
        now = time.time()
        timeout = timeout_override if timeout_override is not None else self.timeout_seconds
        deadline_at = now + timeout

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO ipc_messages
            (message_id, target, status, payload, sent_at, deadline_at,
             attempt_count, conversation_id, message_type, from_agent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                target,
                MessageStatus.SENT.value,
                payload,
                now,
                deadline_at,
                1,
                conversation_id,
                message_type,
                from_agent,
                now,
                now,
            ),
        )
        conn.commit()
        logger.debug("Recorded send: %s -> %s (deadline: %.1fs)", message_id, target, timeout)

        return MessageState(
            message_id=message_id,
            target=target,
            status=MessageStatus.SENT,
            payload=payload,
            sent_at=now,
            deadline_at=deadline_at,
            attempt_count=1,
            last_retry_at=None,
            conversation_id=conversation_id,
            message_type=message_type,
            from_agent=from_agent,
            created_at=now,
            updated_at=now,
        )

    def mark_acked(self, message_id: str, reason: str = "") -> bool:
        """Mark message as acknowledged. Returns True if updated."""
        now = time.time()
        conn = self._get_conn()
        cursor = conn.execute(
            """
            UPDATE ipc_messages
            SET status = ?, updated_at = ?
            WHERE message_id = ? AND status IN (?, ?)
            """,
            (MessageStatus.ACKED.value, now, message_id, MessageStatus.SENT.value, MessageStatus.RETRIED.value),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.info("Message acked: %s %s", message_id, f"({reason})" if reason else "")
        return updated

    def mark_timeout(self, message_id: str) -> bool:
        """Mark message as timed out. Returns True if updated."""
        now = time.time()
        conn = self._get_conn()
        cursor = conn.execute(
            """
            UPDATE ipc_messages
            SET status = ?, updated_at = ?
            WHERE message_id = ? AND status IN (?, ?)
            """,
            (MessageStatus.TIMEOUT.value, now, message_id, MessageStatus.SENT.value, MessageStatus.RETRIED.value),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.warning("Message timeout: %s", message_id)
        return updated

    def mark_retried(self, message_id: str) -> tuple[bool, float]:
        """Mark message as retried with new deadline. Returns (updated, new_deadline)."""
        now = time.time()
        # Exponential backoff: backoff * (2 ^ attempt_count)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT attempt_count, created_at FROM ipc_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()

        if not row:
            return False, 0.0

        attempt_count = row["attempt_count"]
        created_at = row["created_at"]

        # Check retry window
        if now - created_at > self.retry_window_seconds:
            self.mark_failed(message_id, "retry_window_exceeded")
            return False, 0.0

        # Check max retries
        if attempt_count >= self.max_retries:
            self.mark_failed(message_id, "max_retries_exceeded")
            return False, 0.0

        new_attempt = attempt_count + 1
        backoff = self.retry_backoff_seconds * (2 ** (new_attempt - 1))
        new_deadline = now + backoff

        cursor = conn.execute(
            """
            UPDATE ipc_messages
            SET status = ?, attempt_count = ?, deadline_at = ?, last_retry_at = ?, updated_at = ?
            WHERE message_id = ?
            """,
            (MessageStatus.RETRIED.value, new_attempt, new_deadline, now, now, message_id),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.info("Message retried: %s (attempt %d, next deadline in %.1fs)", message_id, new_attempt, backoff)
        return updated, new_deadline

    def mark_failed(self, message_id: str, reason: str = "") -> bool:
        """Mark message as permanently failed. Returns True if updated."""
        now = time.time()
        conn = self._get_conn()
        cursor = conn.execute(
            """
            UPDATE ipc_messages
            SET status = ?, updated_at = ?
            WHERE message_id = ? AND status != ?
            """,
            (MessageStatus.FAILED.value, now, message_id, MessageStatus.ACKED.value),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.error("Message failed: %s %s", message_id, f"({reason})" if reason else "")
        return updated

    def get_pending_timeouts(self, now: float | None = None) -> list[MessageState]:
        """Get messages that have passed their deadline and need timeout handling."""
        if now is None:
            now = time.time()
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM ipc_messages
            WHERE status IN (?, ?) AND deadline_at <= ?
            ORDER BY deadline_at ASC
            """,
            (MessageStatus.SENT.value, MessageStatus.RETRIED.value, now),
        ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def get_by_id(self, message_id: str) -> MessageState | None:
        """Get message state by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM ipc_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return self._row_to_state(row) if row else None

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about message states."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM ipc_messages
            GROUP BY status
            """
        ).fetchall()
        stats = {row["status"]: row["count"] for row in rows}
        return {
            "total": sum(stats.values()),
            "by_status": stats,
            "pending": stats.get(MessageStatus.SENT.value, 0) + stats.get(MessageStatus.RETRIED.value, 0),
            "acked": stats.get(MessageStatus.ACKED.value, 0),
            "failed": stats.get(MessageStatus.FAILED.value, 0),
        }

    def cleanup_old(self, max_age_seconds: float = 86400 * 7) -> int:
        """Remove old completed/failed messages. Returns count deleted."""
        cutoff = time.time() - max_age_seconds
        conn = self._get_conn()
        cursor = conn.execute(
            """
            DELETE FROM ipc_messages
            WHERE status IN (?, ?) AND updated_at < ?
            """,
            (MessageStatus.ACKED.value, MessageStatus.FAILED.value, cutoff),
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old messages", deleted)
        return deleted

    def _row_to_state(self, row: sqlite3.Row) -> MessageState:
        return MessageState(
            message_id=row["message_id"],
            target=row["target"],
            status=MessageStatus(row["status"]),
            payload=row["payload"],
            sent_at=row["sent_at"],
            deadline_at=row["deadline_at"],
            attempt_count=row["attempt_count"],
            last_retry_at=row["last_retry_at"],
            conversation_id=row["conversation_id"],
            message_type=row["message_type"],
            from_agent=row["from_agent"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
