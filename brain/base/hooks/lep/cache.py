#!/usr/bin/env python3
"""LEP Engine - Configuration Caching with mtime-based Invalidation"""

import os
from typing import Optional
from dataclasses import dataclass

from lep import LepConfig, get_lep_path, load_lep


@dataclass
class CachedConfig:
    """Cached LEP configuration with metadata"""
    config: LepConfig
    mtime: float
    path: str


# Module-level cache (thread-safe in CPython due to GIL)
_CACHE: Optional[CachedConfig] = None


def get_lep_config(path: str | None = None) -> LepConfig:
    """Get LEP config with mtime-based caching

    Args:
        path: Path to lep.yaml file

    Returns:
        LepConfig: Loaded configuration

    Notes:
        - Config is cached and only reloaded if file mtime changes
        - Returns empty config if file doesn't exist (fail-safe)
        - Thread-safe due to Python GIL
    """
    global _CACHE

    if path is None:
        path = get_lep_path()

    # Check if file exists
    if not os.path.exists(path):
        # Return empty config (fail-safe)
        return LepConfig(actions={}, gates={}, command_mapping=None)

    # Get current mtime
    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        # File disappeared or not accessible
        return LepConfig(actions={}, gates={}, command_mapping=None)

    # Check cache
    if _CACHE is not None:
        if _CACHE.path == path and _CACHE.mtime == current_mtime:
            # Cache hit - return cached config
            return _CACHE.config

    # Cache miss or invalidated - reload
    try:
        config = load_lep(path)
        _CACHE = CachedConfig(config=config, mtime=current_mtime, path=path)
        return config
    except Exception:
        # Load failed - return empty config (fail-safe)
        return LepConfig(actions={}, gates={}, command_mapping=None)


def invalidate_cache():
    """Invalidate the config cache (force reload on next access)"""
    global _CACHE
    _CACHE = None


def get_cache_info() -> Optional[dict]:
    """Get cache information for debugging

    Returns:
        dict with cache metadata or None if no cache
    """
    if _CACHE is None:
        return None

    return {
        'path': _CACHE.path,
        'mtime': _CACHE.mtime,
        'gates_count': len(_CACHE.config.gates),
        'actions_count': len(_CACHE.config.actions),
    }


__all__ = [
    "get_lep_config",
    "invalidate_cache",
    "get_cache_info",
    "CachedConfig",
]
