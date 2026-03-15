#!/usr/bin/env python3
"""Tool Validation Handler V2 - YAML-Driven

This is the simplified handler that delegates all gate logic to LepEngine.
The engine reads gates from /brain/base/spec/core/lep.yaml and executes them dynamically.

Key improvements over V1:
- 759 lines → ~100 lines (87% reduction)
- All gate logic in lep.yaml, not hardcoded
- Adding new gates requires only YAML config, no code changes
"""

import sys
import os
from pathlib import Path

# Add modules to path
# 优先使用环境变量 HOOK_ROOT，否则使用计算路径
_HOOK_ROOT = os.environ.get("HOOK_ROOT")
if _HOOK_ROOT:
    SERVICE_ROOT = Path(_HOOK_ROOT)
else:
    # __file__ = agent_abilities/src/hooks/handlers/tool_validation/current/python/handler.py
    # 5 parents = agent_abilities/src/hooks/
    # 6 parents = agent_abilities/src/
    # 7 parents = agent_abilities/  ← SERVICE_ROOT (what LepEngine expects as hook_root)
    SERVICE_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent.parent  # agent_abilities/

HOOKS_SRC    = Path(__file__).parent.parent.parent.parent.parent          # src/hooks/
sys.path.insert(0, str(HOOKS_SRC / "lep"))
sys.path.insert(0, str(HOOKS_SRC / "utils" / "python"))
sys.path.insert(0, str(HOOKS_SRC / "checkers" / "audit_logger" / "current" / "python"))

try:
    from engine import LepEngine
    from cache import get_lep_config
    from io_helper import load_json_input, output_block, output_warn, output_pass
    from logger import log_tool_use
except ImportError as e:
    print(f"Critical: Failed to import required modules: {e}", file=sys.stderr)
    print(f"sys.path: {sys.path}", file=sys.stderr)
    sys.exit(0)  # Fail-safe: allow operation on import error


# Global engine instance (lazy-initialized)
_ENGINE = None


def get_engine():
    """Get or create the global LepEngine instance

    Returns:
        LepEngine: Initialized engine with current LEP config
    """
    global _ENGINE

    if _ENGINE is None:
        try:
            lep_config = get_lep_config()
            _ENGINE = LepEngine(lep_config, SERVICE_ROOT)
        except Exception as e:
            print(f"Warning: Failed to initialize LepEngine: {e}", file=sys.stderr)
            # Return None on failure - handler will fail-safe to pass
            return None

    return _ENGINE


def handle_pre_tool_use():
    """PreToolUse: YAML-driven validation

    Flow:
        1. Load JSON input from stdin
        2. Get LepEngine instance
        3. Execute engine.check()
        4. Handle result (block/warn/pass)
        5. Log audit trail
    """
    try:
        # 1. Load input
        data = load_json_input()
        tool_name = data.get("tool_name", data.get("toolName", ""))
        tool_input = data.get("tool_input", data.get("toolInput", {}))

        # 2. Get engine
        engine = get_engine()

        if engine is None:
            # Engine failed to initialize - fail-safe to pass
            print("Warning: LepEngine not available, allowing operation", file=sys.stderr)
            log_tool_use("PreToolUse", tool_name, tool_input, warned=True, gate="ENGINE_INIT_FAILED")
            output_pass("PreToolUse")
            sys.exit(0)

        # 3. Execute checks
        result = engine.check(tool_name, tool_input)

        # 4. Handle result
        if result.is_block:
            # BLOCK: Stop operation
            log_tool_use("PreToolUse", tool_name, tool_input, blocked=True, gate=result.gate_id)
            output_block("PreToolUse", result.message)
            sys.exit(0)

        elif result.is_warn:
            # WARN: Show warning but continue
            log_tool_use("PreToolUse", tool_name, tool_input, warned=True, gate=result.gate_id)
            output_warn("PreToolUse", result.message)

        # 5. Log and pass
        log_tool_use("PreToolUse", tool_name, tool_input)
        output_pass("PreToolUse")
        sys.exit(0)

    except Exception as e:
        # Fail-safe: errors should not block operations
        print(f"PreToolUse handler error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)


def handle_post_tool_use():
    """PostToolUse: Audit logging only

    V2 currently only logs tool usage in PostToolUse.
    Future enhancements could add post-execution checks here.
    """
    try:
        data = load_json_input()
        tool_name = data.get("tool_name", data.get("toolName", ""))
        tool_input = data.get("tool_input", data.get("toolInput", {}))

        # Log tool usage
        log_tool_use("PostToolUse", tool_name, tool_input)

        # Pass
        output_pass("PostToolUse")
        sys.exit(0)

    except Exception as e:
        # Fail-safe
        print(f"PostToolUse handler error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    # Determine which handler to run based on script name
    if "pre_tool_use" in sys.argv[0]:
        handle_pre_tool_use()
    elif "post_tool_use" in sys.argv[0]:
        handle_post_tool_use()
    else:
        # Default to pre_tool_use
        handle_pre_tool_use()
