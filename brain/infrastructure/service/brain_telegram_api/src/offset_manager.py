"""Offset manager for Telegram polling (prevents duplicate messages)."""

import sqlite3
import logging
import os
from threading import Lock
from datetime import datetime

logger = logging.getLogger("offset_manager")


class OffsetManager:
    """Manages Telegram update offset for long polling."""

    def __init__(self, db_path: str):
        """Initialize offset manager.

        Args:
            db_path: SQLite database file path
        """
        self.db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS offsets (
                    id INTEGER PRIMARY KEY,
                    platform TEXT UNIQUE,
                    offset INTEGER,
                    last_update TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()
            logger.info(f"Offset database initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize offset database: {e}")
            raise

    def get_offset(self) -> int:
        """Get current offset value.

        Returns:
            Current offset (default 0 if not set)
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    "SELECT offset FROM offsets WHERE platform = ?",
                    ("telegram",)
                )
                row = cursor.fetchone()
                conn.close()

                if row:
                    offset = row[0]
                    logger.debug(f"Retrieved offset: {offset}")
                    return offset
                else:
                    logger.info("No offset found, starting from 0")
                    return 0
            except Exception as e:
                logger.error(f"Failed to get offset: {e}")
                return 0

    def update(self, update_id: int):
        """Update offset to latest update ID.

        Args:
            update_id: Latest Telegram update ID
        """
        with self._lock:
            # Offset = update_id + 1 (to fetch next update)
            next_offset = update_id + 1

            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute('''
                    INSERT OR REPLACE INTO offsets (platform, offset, last_update)
                    VALUES (?, ?, ?)
                ''', ("telegram", next_offset, datetime.utcnow().isoformat()))
                conn.commit()
                conn.close()
                logger.debug(f"Updated offset to: {next_offset}")
            except Exception as e:
                logger.error(f"Failed to update offset: {e}")

    def get_stats(self) -> dict:
        """Get offset manager statistics.

        Returns:
            Dictionary with stats
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    "SELECT offset, last_update FROM offsets WHERE platform = ?",
                    ("telegram",)
                )
                row = cursor.fetchone()
                conn.close()

                if row:
                    return {
                        "current_offset": row[0],
                        "last_update": row[1]
                    }
                else:
                    return {
                        "current_offset": 0,
                        "last_update": None
                    }
            except Exception as e:
                logger.error(f"Failed to get stats: {e}")
                return {}
