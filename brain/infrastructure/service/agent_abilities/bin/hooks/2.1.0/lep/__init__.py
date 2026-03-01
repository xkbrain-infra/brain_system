#!/usr/bin/env python3
"""LEP Engine - Linear Expression Protocol Enforcement

This module provides YAML-driven gate enforcement for Brain hooks.
"""

# Re-export from lep module (the original lep.py)
from .lep import (
    LepConfig,
    LEP_FILE_DEFAULT,
    load_lep,
    expand_applies_to,
    gate_applies,
)

# Re-export from new modules
from .result import (
    CheckStatus,
    CheckResult,
    GateMatch,
    CheckContext,
)

from .engine import (
    LepEngine,
    PRIORITY_ORDER,
)

from .cache import (
    get_lep_config,
    invalidate_cache,
    get_cache_info,
)

__all__ = [
    # Original lep.py exports
    "LepConfig",
    "LEP_FILE_DEFAULT",
    "load_lep",
    "expand_applies_to",
    "gate_applies",
    # Result types
    "CheckStatus",
    "CheckResult",
    "GateMatch",
    "CheckContext",
    # Engine
    "LepEngine",
    "PRIORITY_ORDER",
    # Cache
    "get_lep_config",
    "invalidate_cache",
    "get_cache_info",
]
