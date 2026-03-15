"""Config store module for atomic hot reload.

Holds current_config, last_known_good, and version tracking.
Provides compare-and-swap (CAS) for atomic commits.
"""

import threading
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("config_store")


@dataclass
class ConfigVersion:
    """Configuration version with metadata."""
    version: int
    config: Dict[str, Any]
    runtime: Any = None  # Runtime object built from config
    timestamp: float = field(default_factory=time.time)


class ConfigStore:
    """Thread-safe configuration store with version tracking."""

    def __init__(self):
        self._lock = threading.RLock()
        self._current: Optional[ConfigVersion] = None
        self._last_known_good: Optional[ConfigVersion] = None
        self._version_counter = 0

    @property
    def current(self) -> Optional[Dict[str, Any]]:
        """Get current configuration."""
        with self._lock:
            return self._current.config if self._current else None

    @property
    def version(self) -> int:
        """Get current configuration version."""
        with self._lock:
            return self._current.version if self._current else 0

    @property
    def runtime(self) -> Any:
        """Get current runtime object."""
        with self._lock:
            return self._current.runtime if self._current else None

    @property
    def last_known_good(self) -> Optional[Dict[str, Any]]:
        """Get last known good configuration."""
        with self._lock:
            return self._last_known_good.config if self._last_known_good else None

    @last_known_good.setter
    def last_known_good(self, config: Optional[Dict[str, Any]]):
        """Set last known good configuration."""
        with self._lock:
            if config is not None:
                self._last_known_good = ConfigVersion(
                    version=self._version_counter,
                    config=config
                )

    def initialize(self, config: Dict[str, Any], runtime: Any = None):
        """Initialize with configuration.

        Args:
            config: Initial configuration
            runtime: Initial runtime object
        """
        with self._lock:
            self._version_counter += 1
            self._current = ConfigVersion(
                version=self._version_counter,
                config=config,
                runtime=runtime
            )
            self._last_known_good = ConfigVersion(
                version=self._version_counter,
                config=config
            )
            logger.info(f"ConfigStore initialized, version={self._version_counter}")

    def compare_and_swap(
        self,
        expected_version: int,
        new_config: Dict[str, Any],
        new_runtime: Any = None
    ) -> bool:
        """Atomic compare-and-swap operation.

        Args:
            expected_version: Expected current version
            new_config: New configuration
            new_runtime: New runtime object

        Returns:
            True if swap succeeded, False if version mismatch
        """
        with self._lock:
            if self._current is None:
                logger.warning("ConfigStore not initialized")
                return False

            if self._current.version != expected_version:
                logger.warning(
                    f"Version mismatch: expected={expected_version}, current={self._current.version}"
                )
                return False

            # Save current as last known good before updating
            self._last_known_good = ConfigVersion(
                version=self._current.version,
                config=self._current.config,
                runtime=self._current.runtime
            )

            # Atomic commit: update current
            self._version_counter += 1
            self._current = ConfigVersion(
                version=self._version_counter,
                config=new_config,
                runtime=new_runtime
            )

            logger.info(
                f"Config committed: version {expected_version} -> {self._version_counter}"
            )
            return True

    def restore(self, config: Dict[str, Any], version: int):
        """Restore to a previous configuration.

        Args:
            config: Configuration to restore
            version: Version to restore
        """
        with self._lock:
            self._current = ConfigVersion(
                version=version,
                config=config,
                runtime=None  # Runtime will be rebuilt
            )
            logger.info(f"Config restored to version {version}")


# Global config store instance
_config_store = ConfigStore()


def get_config_store() -> ConfigStore:
    """Get global config store instance."""
    return _config_store
