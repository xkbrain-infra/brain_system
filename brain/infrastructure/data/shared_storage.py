"""Shared SQLite Storage for Brain System.

This module provides a shared database for cross-service data:
- Agent registry (current state of all agents)
- IPC message log (optional audit trail)
- Global configuration

Services should import SharedStorage for shared data access,
and use their own service-specific databases for high-frequency writes.
"""

import sqlite3
import time
import logging
from pathlib import Path
from typing import Any
from contextlib import contextmanager

logger = logging.getLogger("brain.shared_storage")

# Default path for shared database
DEFAULT_SHARED_DB = "/brain/infrastructure/data/db/brain_shared.db"


class SharedStorage:
    """Shared SQLite storage for brain system."""

    _instance: "SharedStorage | None" = None

    def __init__(self, db_path: str = DEFAULT_SHARED_DB) -> None:
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_schema()

    @classmethod
    def get_instance(cls, db_path: str = DEFAULT_SHARED_DB) -> "SharedStorage":
        """Get singleton instance."""
        if cls._instance is None or cls._instance.db_path != db_path:
            cls._instance = cls(db_path)
        return cls._instance

    def _ensure_db_dir(self) -> None:
        """Ensure database directory exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_conn(self):
        """Get database connection with WAL mode for better concurrency."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent reads
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.executescript("""
                -- Agent registry: current state of all known agents
                CREATE TABLE IF NOT EXISTS agents (
                    instance_id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    agent_type TEXT DEFAULT 'unknown',  -- heartbeat, tmux_discovery, register
                    online INTEGER NOT NULL DEFAULT 1,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    last_heartbeat INTEGER,
                    tmux_session TEXT,
                    tmux_pane TEXT,
                    metadata TEXT  -- JSON for extra fields
                );

                CREATE INDEX IF NOT EXISTS idx_agents_name
                ON agents(agent_name);

                CREATE INDEX IF NOT EXISTS idx_agents_online
                ON agents(online, last_seen);

                -- IPC message log (audit trail, optional)
                CREATE TABLE IF NOT EXISTS ipc_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT UNIQUE,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    message_type TEXT,
                    content TEXT,
                    created_at INTEGER NOT NULL,
                    delivered_at INTEGER,
                    acked_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_ipc_from
                ON ipc_messages(from_agent, created_at);

                CREATE INDEX IF NOT EXISTS idx_ipc_to
                ON ipc_messages(to_agent, created_at);

                -- Global configuration key-value store
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at INTEGER NOT NULL
                );

                -- Session to agent mapping (for context tracking)
                CREATE TABLE IF NOT EXISTS session_mapping (
                    session_id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    instance_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_session_agent
                ON session_mapping(agent_name);
            """)
            conn.commit()
        logger.info(f"Shared database initialized: {self.db_path}")

    # ============ Agent Registry ============

    def upsert_agent(
        self,
        instance_id: str,
        agent_name: str,
        agent_type: str = "unknown",
        online: bool = True,
        tmux_session: str | None = None,
        tmux_pane: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any] | None:
        """Update or insert agent, return previous state if online changed."""
        import json
        now = int(time.time())

        with self._get_conn() as conn:
            # Get previous state
            row = conn.execute(
                "SELECT * FROM agents WHERE instance_id = ?",
                (instance_id,)
            ).fetchone()

            prev_state = dict(row) if row else None
            online_int = 1 if online else 0

            if prev_state:
                # Update existing
                conn.execute("""
                    UPDATE agents
                    SET agent_name = ?, agent_type = ?, online = ?, last_seen = ?,
                        last_heartbeat = ?, tmux_session = ?, tmux_pane = ?, metadata = ?
                    WHERE instance_id = ?
                """, (
                    agent_name, agent_type, online_int, now, now,
                    tmux_session, tmux_pane,
                    json.dumps(metadata) if metadata else None,
                    instance_id
                ))
            else:
                # Insert new
                conn.execute("""
                    INSERT INTO agents
                    (instance_id, agent_name, agent_type, online, first_seen, last_seen,
                     last_heartbeat, tmux_session, tmux_pane, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    instance_id, agent_name, agent_type, online_int, now, now, now,
                    tmux_session, tmux_pane,
                    json.dumps(metadata) if metadata else None
                ))

            conn.commit()

            # Return previous state if online status changed
            if prev_state and prev_state["online"] != online_int:
                return prev_state
            return None

    def get_agent(self, instance_id: str) -> dict[str, Any] | None:
        """Get agent by instance ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE instance_id = ?",
                (instance_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_agent_by_name(self, agent_name: str) -> list[dict[str, Any]]:
        """Get all agents with given name (may have multiple instances)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE agent_name = ? ORDER BY last_seen DESC",
                (agent_name,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_agents(self, online_only: bool = False) -> list[dict[str, Any]]:
        """Get all agents."""
        with self._get_conn() as conn:
            if online_only:
                rows = conn.execute(
                    "SELECT * FROM agents WHERE online = 1 ORDER BY agent_name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agents ORDER BY agent_name"
                ).fetchall()
            return [dict(row) for row in rows]

    def mark_agent_offline(self, instance_id: str) -> None:
        """Mark agent as offline."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE agents SET online = 0, last_seen = ? WHERE instance_id = ?",
                (now, instance_id)
            )
            conn.commit()

    # ============ IPC Message Log ============

    def log_ipc_message(
        self,
        msg_id: str,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str | None = None,
    ) -> None:
        """Log an IPC message (for audit trail)."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO ipc_messages
                (msg_id, from_agent, to_agent, message_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (msg_id, from_agent, to_agent, message_type, content, now))
            conn.commit()

    def mark_ipc_delivered(self, msg_id: str) -> None:
        """Mark IPC message as delivered."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ipc_messages SET delivered_at = ? WHERE msg_id = ?",
                (now, msg_id)
            )
            conn.commit()

    def mark_ipc_acked(self, msg_id: str) -> None:
        """Mark IPC message as acknowledged."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ipc_messages SET acked_at = ? WHERE msg_id = ?",
                (now, msg_id)
            )
            conn.commit()

    def get_ipc_messages(
        self,
        agent_name: str | None = None,
        direction: str = "both",  # "from", "to", "both"
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get IPC messages for an agent."""
        with self._get_conn() as conn:
            if agent_name is None:
                rows = conn.execute(
                    "SELECT * FROM ipc_messages ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            elif direction == "from":
                rows = conn.execute(
                    "SELECT * FROM ipc_messages WHERE from_agent LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{agent_name}%", limit)
                ).fetchall()
            elif direction == "to":
                rows = conn.execute(
                    "SELECT * FROM ipc_messages WHERE to_agent LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{agent_name}%", limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM ipc_messages
                       WHERE from_agent LIKE ? OR to_agent LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (f"%{agent_name}%", f"%{agent_name}%", limit)
                ).fetchall()
            return [dict(row) for row in rows]

    # ============ Config ============

    def set_config(self, key: str, value: str) -> None:
        """Set config value."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO config (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """, (key, value, now, value, now))
            conn.commit()

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Get config value."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?",
                (key,)
            ).fetchone()
            return row["value"] if row else default

    def get_all_config(self) -> dict[str, str]:
        """Get all config as dict."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
            return {row["key"]: row["value"] for row in rows}

    # ============ Session Mapping ============

    def set_session_mapping(
        self,
        session_id: str,
        agent_name: str,
        instance_id: str | None = None,
    ) -> None:
        """Map a Claude session ID to an agent name."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO session_mapping (session_id, agent_name, instance_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_name = ?, instance_id = ?, updated_at = ?
            """, (session_id, agent_name, instance_id, now, now, agent_name, instance_id, now))
            conn.commit()

    def get_session_mapping(self, session_id: str) -> dict[str, Any] | None:
        """Get agent name for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM session_mapping WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_sessions_by_agent(self, agent_name: str) -> list[dict[str, Any]]:
        """Get all sessions for an agent."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM session_mapping WHERE agent_name = ?",
                (agent_name,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ============ Cleanup ============

    def cleanup_old_data(self, days: int = 30) -> int:
        """Clean up old IPC messages. Returns deleted count."""
        cutoff = int(time.time()) - (days * 86400)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM ipc_messages WHERE created_at < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def cleanup_stale_agents(self, stale_hours: int = 24) -> int:
        """Mark agents as offline if not seen recently."""
        cutoff = int(time.time()) - (stale_hours * 3600)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE agents SET online = 0 WHERE online = 1 AND last_seen < ?",
                (cutoff,)
            )
            updated = cursor.rowcount
            conn.commit()
            return updated
