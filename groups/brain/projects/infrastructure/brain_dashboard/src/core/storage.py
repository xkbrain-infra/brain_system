"""SQLite Storage for Agent Dashboard.

This is the service-specific database for dashboard.
High-frequency time-series data (snapshots, context usage, alerts) stays here.
Agent state is managed by the shared database (brain_shared.db).
"""

import sqlite3
import time
import logging
from pathlib import Path
from typing import Any
from contextlib import contextmanager

# Shared storage is provided via PYTHONPATH
from shared_storage import SharedStorage

logger = logging.getLogger("agent_dashboard.storage")

# Default paths
DEFAULT_DASHBOARD_DB = "/xkagent_infra/runtime/data/services/dashboard.db"
DEFAULT_SHARED_DB = "/xkagent_infra/runtime/data/brain_shared.db"


class Storage:
    """SQLite storage for dashboard metrics and alerts.

    Uses two databases:
    - dashboard.db: High-frequency time-series data (snapshots, context, alerts)
    - brain_shared.db: Shared agent state (via SharedStorage)
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DASHBOARD_DB,
        shared_db_path: str = DEFAULT_SHARED_DB,
        retention_days: int = 7,
    ) -> None:
        self.db_path = db_path
        self.retention_days = retention_days
        self._ensure_db_dir()
        self._init_schema()
        # Initialize shared storage
        self.shared = SharedStorage.get_instance(shared_db_path)

    def _ensure_db_dir(self) -> None:
        """Ensure database directory exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_conn(self):
        """Get database connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Initialize database schema (dashboard-specific tables only)."""
        with self._get_conn() as conn:
            conn.executescript("""
                -- Time-series snapshots (high frequency writes)
                CREATE TABLE IF NOT EXISTS agent_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    source TEXT DEFAULT 'unknown',
                    online INTEGER NOT NULL,
                    registered_at INTEGER,
                    last_heartbeat INTEGER,
                    idle_seconds INTEGER,
                    tmux_session TEXT,
                    tmux_pane TEXT,
                    collected_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_agent_time
                ON agent_snapshots(agent_name, collected_at);

                -- Alerts history
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    instance_id TEXT,
                    alert_type TEXT NOT NULL,
                    message TEXT,
                    created_at INTEGER NOT NULL,
                    sent_at INTEGER,
                    cooldown_until INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_agent
                ON alerts(agent_name, created_at);

                -- Context usage time-series
                CREATE TABLE IF NOT EXISTS context_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    instance_id TEXT,
                    model TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cache_read_tokens INTEGER,
                    cache_creation_tokens INTEGER,
                    total_context INTEGER,
                    context_window INTEGER,
                    usage_percent REAL,
                    collected_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_context_session_time
                ON context_usage(session_id, collected_at);

                -- Traffic monitoring time-series
                CREATE TABLE IF NOT EXISTS traffic_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    ipc_total_sent INTEGER DEFAULT 0,
                    ipc_total_received INTEGER DEFAULT 0,
                    ipc_bytes INTEGER DEFAULT 0,
                    ipc_errors INTEGER DEFAULT 0,
                    api_total_requests INTEGER DEFAULT 0,
                    api_errors INTEGER DEFAULT 0,
                    api_error_rate REAL DEFAULT 0.0,
                    cpu_percent REAL DEFAULT 0.0,
                    memory_percent REAL DEFAULT 0.0
                );

                CREATE INDEX IF NOT EXISTS idx_traffic_time
                ON traffic_snapshots(timestamp);
            """)
            conn.commit()
        logger.info(f"Dashboard database initialized: {self.db_path}")

    def save_snapshot(self, agent: dict[str, Any], collected_at: int) -> None:
        """Save agent snapshot."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO agent_snapshots
                (agent_name, instance_id, source, online, registered_at, last_heartbeat,
                 idle_seconds, tmux_session, tmux_pane, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent.get("agent_name", agent.get("name", "")),
                agent.get("instance_id", ""),
                agent.get("source", "unknown"),
                1 if agent.get("online") else 0,
                agent.get("registered_at"),
                agent.get("last_heartbeat"),
                agent.get("idle_seconds"),
                agent.get("tmux_session"),
                agent.get("tmux_pane"),
                collected_at,
            ))
            conn.commit()

    def update_agent_state(self, agent: dict[str, Any], now: int) -> dict[str, Any] | None:
        """Update agent state in shared database and return previous state if changed.

        Delegates to SharedStorage for cross-service visibility.
        """
        instance_id = agent.get("instance_id", "")
        agent_name = agent.get("agent_name", agent.get("name", ""))
        source = agent.get("source", "unknown")
        online = agent.get("online", True)

        # Use shared storage for agent state
        return self.shared.upsert_agent(
            instance_id=instance_id,
            agent_name=agent_name,
            agent_type=source,
            online=online,
            tmux_session=agent.get("tmux_session"),
            tmux_pane=agent.get("tmux_pane"),
        )

    def get_latest_agents(self, online_only: bool = False) -> list[dict[str, Any]]:
        """Get latest state of all agents from shared database."""
        return self.shared.get_all_agents(online_only=online_only)

    def get_agent_history(
        self, agent_name: str, hours: int = 24
    ) -> list[dict[str, Any]]:
        """Get agent history for the past N hours."""
        since = int(time.time()) - (hours * 3600)
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM agent_snapshots
                WHERE agent_name = ? AND collected_at >= ?
                ORDER BY collected_at
            """, (agent_name, since)).fetchall()
            return [dict(row) for row in rows]

    def save_alert(
        self,
        agent_name: str,
        instance_id: str,
        alert_type: str,
        message: str,
        cooldown_until: int,
    ) -> int:
        """Save alert and return alert ID."""
        now = int(time.time())
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO alerts (agent_name, instance_id, alert_type, message, created_at, cooldown_until)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_name, instance_id, alert_type, message, now, cooldown_until))
            conn.commit()
            return cursor.lastrowid

    def mark_alert_sent(self, alert_id: int) -> None:
        """Mark alert as sent."""
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE alerts SET sent_at = ? WHERE id = ?",
                (now, alert_id)
            )
            conn.commit()

    def get_active_cooldown(self, agent_name: str, alert_type: str) -> int | None:
        """Get active cooldown timestamp for agent/alert_type."""
        now = int(time.time())
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT cooldown_until FROM alerts
                WHERE agent_name = ? AND alert_type = ? AND cooldown_until > ?
                ORDER BY cooldown_until DESC LIMIT 1
            """, (agent_name, alert_type, now)).fetchone()
            return row["cooldown_until"] if row else None

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent alerts."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def cleanup_old_data(self) -> int:
        """Delete data older than retention period. Returns deleted count."""
        cutoff = int(time.time()) - (self.retention_days * 86400)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_snapshots WHERE collected_at < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.execute(
                "DELETE FROM alerts WHERE created_at < ?",
                (cutoff,)
            )
            conn.execute(
                "DELETE FROM context_usage WHERE collected_at < ?",
                (cutoff,)
            )
            conn.commit()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old snapshot records")
            return deleted

    def save_context_usage(self, usage: Any, collected_at: int) -> None:
        """Save context usage snapshot."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO context_usage
                (session_id, instance_id, model, input_tokens, output_tokens,
                 cache_read_tokens, cache_creation_tokens, total_context,
                 context_window, usage_percent, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                usage.session_id,
                usage.instance_id,
                usage.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_creation_tokens,
                usage.total_context,
                usage.context_window,
                usage.usage_percent,
                collected_at,
            ))
            conn.commit()

    def get_latest_context_usage(self) -> list[dict[str, Any]]:
        """Get latest context usage for each session."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT c1.* FROM context_usage c1
                INNER JOIN (
                    SELECT session_id, MAX(collected_at) as max_time
                    FROM context_usage GROUP BY session_id
                ) c2 ON c1.session_id = c2.session_id AND c1.collected_at = c2.max_time
                ORDER BY c1.usage_percent DESC
            """).fetchall()
            return [dict(row) for row in rows]

    def get_context_history(self, session_id: str, hours: int = 24) -> list[dict[str, Any]]:
        """Get context usage history for a session."""
        since = int(time.time()) - (hours * 3600)
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM context_usage
                WHERE session_id = ? AND collected_at >= ?
                ORDER BY collected_at
            """, (session_id, since)).fetchall()
            return [dict(row) for row in rows]

    def save_traffic_snapshot(self, data: dict) -> None:
        """Save traffic snapshot to database."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO traffic_snapshots
                (timestamp, ipc_total_sent, ipc_total_received, ipc_bytes, ipc_errors,
                 api_total_requests, api_errors, api_error_rate, cpu_percent, memory_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("timestamp"),
                data.get("ipc_total_sent", 0),
                data.get("ipc_total_received", 0),
                data.get("ipc_bytes", 0),
                data.get("ipc_errors", 0),
                data.get("api_total_requests", 0),
                data.get("api_errors", 0),
                data.get("api_error_rate", 0.0),
                data.get("cpu_percent", 0.0),
                data.get("memory_percent", 0.0),
            ))
            conn.commit()

    def get_traffic_history(self, minutes: int = 60) -> list[dict[str, Any]]:
        """Get traffic history for the past N minutes."""
        since = int(time.time()) - (minutes * 60)
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM traffic_snapshots
                WHERE timestamp >= ?
                ORDER BY timestamp
            """, (since,)).fetchall()
            return [dict(row) for row in rows]
