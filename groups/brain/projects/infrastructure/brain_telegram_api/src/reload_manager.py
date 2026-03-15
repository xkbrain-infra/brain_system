"""Reload manager for atomic hot reload with SIGHUP support.

Implements two-phase atomic switch:
1. Load and validate new config
2. Build new runtime (dry run)
3. Atomic commit with CAS
4. On failure: rollback to last_known_good
"""

import asyncio
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass

import yaml

from config_store import get_config_store

logger = logging.getLogger("reload_manager")

# Default timeout for reload operations (seconds)
DEFAULT_RELOAD_TIMEOUT = 30


@dataclass
class ReloadResult:
    """Result of a reload operation."""
    success: bool
    from_version: int
    to_version: int
    trigger: str
    error: Optional[str] = None


class ReloadManager:
    """Manager for atomic configuration reload with SIGHUP support."""

    def __init__(
        self,
        config_path: str,
        validate_fn: Callable[[Dict], Any],
        build_runtime_fn: Callable[[Dict], Any],
        on_reload_callback: Callable[[List, List, List], Any] = None,
        timeout_seconds: int = DEFAULT_RELOAD_TIMEOUT
    ):
        """Initialize reload manager.

        Args:
            config_path: Path to configuration file (bots.yaml)
            validate_fn: Function to validate configuration, returns (ok, error_message)
            build_runtime_fn: Function to build runtime from config, returns runtime object
            on_reload_callback: Callback called after successful reload
            timeout_seconds: Timeout for reload operations (default 30s)
        """
        self.config_path = config_path
        self.validate_fn = validate_fn
        self.build_runtime_fn = build_runtime_fn
        self.on_reload_callback = on_reload_callback
        self._timeout_seconds = timeout_seconds

        self._lock = threading.Lock()
        self._reload_in_progress = False
        self._reload_thread: Optional[threading.Thread] = None

        # Config store
        self._config_store = get_config_store()

        # Thread pool for timeout protection
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reload")

        # Metrics
        self._reload_count = 0
        self._rollback_count = 0

    def start(self):
        """Start SIGHUP signal handler."""
        # Register SIGHUP handler
        signal.signal(signal.SIGHUP, self._handle_sighup)
        logger.info(f"ReloadManager started, watching {self.config_path}")

    def _handle_sighup(self, signum, frame):
        """Handle SIGHUP signal - trigger reload in background."""
        logger.info("Received SIGHUP, scheduling reload")
        if self._reload_in_progress:
            logger.warning("Reload already in progress, skipping")
            return

        # Start reload in background thread
        self._reload_thread = threading.Thread(target=self._do_reload, kwargs={"trigger": "sighup"})
        self._reload_thread.daemon = True
        self._reload_thread.start()

    def trigger_manual_reload(self, trigger: str = "manual") -> ReloadResult:
        """Manually trigger a reload.

        Args:
            trigger: Trigger reason string

        Returns:
            ReloadResult
        """
        if self._reload_in_progress:
            return ReloadResult(
                success=False,
                from_version=0,
                to_version=0,
                trigger=trigger,
                error="Reload already in progress"
            )

        return self._do_reload(trigger=trigger)

    def _do_reload(self, trigger: str = "sighup") -> ReloadResult:
        """Execute reload operation with timeout protection.

        Args:
            trigger: Trigger reason

        Returns:
            ReloadResult
        """
        with self._lock:
            if self._reload_in_progress:
                return ReloadResult(
                    success=False,
                    from_version=0,
                    to_version=0,
                    trigger=trigger,
                    error="Reload already in progress"
                )
            self._reload_in_progress = True

        # Initialize old_version before try block to avoid NameError in except
        old_version = self._config_store.version

        try:
            # Phase 1: Load new config (with timeout)
            logger.info(f"Phase 1: Loading config from {self.config_path}")
            candidate_raw = self._load_config_file()
            if not candidate_raw:
                raise Exception(f"Failed to load config from {self.config_path}")

            # Phase 2: Validate config (with timeout protection)
            logger.info("Phase 2: Validating config")
            valid, error_msg = self._run_with_timeout(
                lambda: self.validate_fn(candidate_raw),
                "validate_fn"
            )
            if not valid:
                raise Exception(f"Config validation failed: {error_msg}")

            # Phase 3: Build new runtime (with timeout protection)
            logger.info("Phase 3: Building new runtime")
            new_runtime = self._run_with_timeout(
                lambda: self.build_runtime_fn(candidate_raw),
                "build_runtime_fn"
            )

            # Get current version
            old_version = self._config_store.version
            old_config = self._config_store.current

            # Phase 4: Atomic commit
            logger.info("Phase 4: Atomic commit")
            committed = self._config_store.compare_and_swap(
                expected_version=old_version,
                new_config=candidate_raw,
                new_runtime=new_runtime
            )

            if not committed:
                raise Exception("Concurrent reload detected, version changed")

            # Success
            new_version = self._config_store.version
            self._reload_count += 1
            logger.info(f"Reload committed: version {old_version} -> {new_version}, trigger={trigger}")

            # Call callback if configured
            if self.on_reload_callback:
                try:
                    # Detect changes for callback
                    added, removed, changed = self._detect_changes(old_config, candidate_raw)
                    self.on_reload_callback(added, removed, changed)
                except Exception as e:
                    logger.error(f"Error in reload callback: {e}")

            return ReloadResult(
                success=True,
                from_version=old_version,
                to_version=new_version,
                trigger=trigger
            )

        except Exception as e:
            # Phase 5: Rollback
            self._rollback_count += 1
            logger.error(f"Reload failed, initiating rollback: {e}")

            # Restore to last known good
            lkg = self._config_store.last_known_good
            lkg_version = self._config_store.version  # Use current version for restore

            if lkg:
                self._config_store.restore(lkg, lkg_version)
                logger.info(f"Rolled back to last known good config")

            return ReloadResult(
                success=False,
                from_version=old_version,
                to_version=self._config_store.version,
                trigger=trigger,
                error=str(e)
            )

        finally:
            with self._lock:
                self._reload_in_progress = False

    def _run_with_timeout(self, func: Callable, func_name: str) -> Any:
        """Run a function with timeout protection.

        Args:
            func: Function to run
            func_name: Function name for logging

        Returns:
            Function result

        Raises:
            Exception: If function times out
        """
        future = self._executor.submit(func)
        try:
            return future.result(timeout=self._timeout_seconds)
        except FuturesTimeoutError:
            raise Exception(f"{func_name} timed out after {self._timeout_seconds}s (fuse blown)")

    def _load_config_file(self) -> Optional[Dict[str, Any]]:
        """Load configuration from file."""
        if not os.path.exists(self.config_path):
            logger.error(f"Config file not found: {self.config_path}")
            return None

        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return None

    def _detect_changes(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any]
    ) -> tuple:
        """Detect configuration changes.

        Returns:
            (added, removed, changed) - lists of bot names
        """
        old_bots = {b['name']: b for b in old_config.get('bots', [])}
        new_bots = {b['name']: b for b in new_config.get('bots', [])}

        old_names = set(old_bots.keys())
        new_names = set(new_bots.keys())

        added = list(new_names - old_names)
        removed = list(old_names - new_names)

        changed = []
        for name in old_names & new_names:
            if old_bots[name] != new_bots[name]:
                changed.append(name)

        return added, removed, changed

    def get_stats(self) -> Dict[str, Any]:
        """Get reload statistics."""
        return {
            "reload_count": self._reload_count,
            "rollback_count": self._rollback_count,
            "current_version": self._config_store.version,
            "reload_in_progress": self._reload_in_progress,
        }

    def stop(self):
        """Stop reload manager."""
        self._executor.shutdown(wait=False)
        logger.info("ReloadManager stopped")


# Helper functions for telegram_api integration
def validate_bots_config(config: Dict[str, Any]) -> tuple:
    """Validate bots configuration.

    Args:
        config: Configuration dictionary

    Returns:
        (valid, error_message)
    """
    if not isinstance(config, dict):
        return False, "Config must be a dictionary"

    bots = config.get('bots', [])
    if not isinstance(bots, list):
        return False, "bots must be a list"

    for bot in bots:
        if not isinstance(bot, dict):
            return False, "Each bot must be a dictionary"

        # Required fields
        if 'name' not in bot:
            return False, "Bot must have name field"
        if 'token_env' not in bot:
            return False, f"Bot {bot.get('name')} missing token_env"

        # Validate platform
        platform = bot.get('platform', 'telegram')
        if platform not in ['telegram']:
            return False, f"Unsupported platform: {platform}"

    return True, None


def build_bots_runtime(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build runtime object from bots configuration.

    This is a dry run - validates config can be converted to runtime.

    Args:
        config: Configuration dictionary

    Returns:
        Runtime dictionary (currently just validates and returns config)
    """
    # In real implementation, this would create actual bot instances
    # For now, just validate we can build the runtime
    runtime = {
        "bots": config.get('bots', []),
        "validated_at": time.time()
    }
    return runtime
