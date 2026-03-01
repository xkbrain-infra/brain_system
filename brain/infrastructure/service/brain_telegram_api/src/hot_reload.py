"""Hot reload module for Telegram API Service.

Monitors bots.yaml configuration file changes and dynamically updates bot instances
without requiring service restart.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    # Fallback: use simple polling-based reload
    import threading

    # Placeholder class when watchdog is not available
    class FileSystemEventHandler:
        pass

logger = logging.getLogger("hot_reload")


class BotConfig:
    """Bot configuration structure."""

    def __init__(self, name: str, token: str, chat_id: str = None,
                 service_name: str = None, platform: str = "telegram",
                 token_env: str = None, chat_id_env: str = None):
        self.name = name
        self.token = token
        self.chat_id = chat_id
        self.service_name = service_name
        self.platform = platform
        self.token_env = token_env
        self.chat_id_env = chat_id_env

    def __repr__(self):
        return f"BotConfig(name={self.name}, platform={self.platform})"

    def __eq__(self, other):
        if not isinstance(other, BotConfig):
            return False
        return (self.name == other.name and
                self.token == other.token and
                self.chat_id == other.chat_id)

    def to_dict(self):
        return {
            "name": self.name,
            "token": self.token,
            "chat_id": self.chat_id,
            "service_name": self.service_name,
            "platform": self.platform,
        }


class BotsReloader:
    """Hot reload handler for bots.yaml configuration."""

    def __init__(self, config_path: str, reload_callback: Callable[[List[BotConfig]], None]):
        """Initialize bots reloader.

        Args:
            config_path: Path to bots.yaml configuration file
            reload_callback: Async callback function called when bots configuration changes.
                           Signature: async function(new_bots: List[BotConfig], removed_bots: List[str])
        """
        self.config_path = config_path
        self.reload_callback = reload_callback
        self._last_config_hash = ""
        self._current_bots: Dict[str, BotConfig] = {}
        self._observer = None
        self._running = False

        # Debounce: ignore multiple events within this window (seconds)
        self._debounce_seconds = 2.0

    def _compute_hash(self, bots: List[dict]) -> str:
        """Compute simple hash of bot configurations."""
        # Use bot names and token env vars as key identifier
        key = "-".join(sorted([f"{b.get('name', '')}:{b.get('token_env', '')}" for b in bots]))
        return str(hash(key))

    def load_bots_config(self) -> List[BotConfig]:
        """Load bots configuration from YAML file.

        Returns:
            List of BotConfig objects
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path}")
            return []

        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)

            bots_list = config.get('bots', [])
            bot_configs = []

            for bot in bots_list:
                name = bot.get('name')
                token_env = bot.get('token_env')
                chat_id_env = bot.get('chat_id_env')
                service_name = bot.get('service_name')
                platform = bot.get('platform', 'telegram')

                # Load token from environment
                token = os.environ.get(token_env) if token_env else None
                if not token:
                    logger.warning(f"Bot '{name}': no token for {token_env}")
                    continue

                chat_id = os.environ.get(chat_id_env) if chat_id_env else None

                bot_configs.append(BotConfig(
                    name=name,
                    token=token.strip(),
                    chat_id=chat_id,
                    service_name=service_name,
                    platform=platform,
                    token_env=token_env,
                    chat_id_env=chat_id_env
                ))

            logger.info(f"Loaded {len(bot_configs)} bots from config")
            return bot_configs

        except Exception as e:
            logger.error(f"Failed to load bots config: {e}")
            return []

    def _detect_changes(self, new_bots: List[BotConfig]) -> tuple:
        """Detect added, removed, and changed bots.

        Returns:
            Tuple of (added_bots, removed_bot_names, changed_bots)
        """
        new_bots_map = {b.name: b for b in new_bots}
        current_names = set(self._current_bots.keys())
        new_names = set(new_bots_map.keys())

        # Added bots
        added = [b for b in new_bots if b.name not in current_names]

        # Removed bots
        removed = list(current_names - new_names)

        # Changed bots (same name but different config)
        changed = []
        for name in current_names & new_names:
            if self._current_bots[name] != new_bots_map[name]:
                changed.append(new_bots_map[name])

        return added, removed, changed

    async def _trigger_reload(self):
        """Trigger configuration reload."""
        logger.info("Detected bots.yaml change, reloading...")

        new_bots = self.load_bots_config()
        added, removed, changed = self._detect_changes(new_bots)

        if not added and not removed and not changed:
            logger.debug("No changes in bot configuration")
            return

        logger.info(f"Bot changes: {len(added)} added, {len(removed)} removed, {len(changed)} changed")

        # Update current bots
        self._current_bots = {b.name: b for b in new_bots}

        # Update hash
        self._last_config_hash = self._compute_hash([b.to_dict() for b in new_bots])

        # Call reload callback
        if self.reload_callback:
            try:
                await self.reload_callback(added, removed, changed)
            except Exception as e:
                logger.error(f"Error in reload callback: {e}")

    def start_watching(self):
        """Start watching configuration file for changes."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file does not exist: {self.config_path}")
            return

        # Load initial configuration
        initial_bots = self.load_bots_config()
        self._current_bots = {b.name: b for b in initial_bots}
        self._last_config_hash = self._compute_hash([b.to_dict() for b in initial_bots])

        if WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            logger.info("watchdog not available, using polling fallback")
            self._start_polling()

    def _start_watchdog(self):
        """Start file watching using watchdog."""
        handler = _FileChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, os.path.dirname(self.config_path), recursive=False)
        self._observer.start()
        self._running = True
        logger.info(f"Started watching {self.config_path} for changes")

    def _start_polling(self):
        """Start polling-based file watching (fallback)."""
        async def poll_loop():
            while self._running:
                try:
                    if os.path.exists(self.config_path):
                        current_mtime = os.path.getmtime(self.config_path)
                        if hasattr(self, '_last_mtime'):
                            if current_mtime != self._last_mtime:
                                self._last_mtime = current_mtime
                                await self._trigger_reload()
                        else:
                            self._last_mtime = current_mtime
                except Exception as e:
                    logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(2)  # Poll every 2 seconds

        # Run polling in background
        asyncio.create_task(poll_loop())
        self._running = True
        logger.info(f"Started polling {self.config_path} for changes")

    def stop_watching(self):
        """Stop watching configuration file."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        logger.info("Stopped watching config file")

    def get_current_bots(self) -> Dict[str, BotConfig]:
        """Get currently loaded bots.

        Returns:
            Dictionary of bot name -> BotConfig
        """
        return self._current_bots.copy()


class _FileChangeHandler(FileSystemEventHandler):
    """File system event handler for watchdog."""

    def __init__(self, reloader: BotsReloader):
        self.reloader = reloader
        self._last_trigger = 0

    def on_modified(self, event):
        """Handle file modification event."""
        if event.is_directory:
            return

        # Check if it's our target file
        if os.path.abspath(event.src_path) == os.path.abspath(self.reloader.config_path):
            import time
            now = time.time()

            # Debounce: ignore events within debounce window
            if now - self._last_trigger < self.reloader._debounce_seconds:
                return

            self._last_trigger = now
            asyncio.create_task(self.reloader._trigger_reload())
