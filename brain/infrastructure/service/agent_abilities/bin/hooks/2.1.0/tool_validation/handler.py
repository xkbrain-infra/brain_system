#!/usr/bin/env python3
"""Tool Validation Handler V2.1 - YAML-Driven + Agent Overrides

V2.1 changes:
- Added agent-specific overrides mechanism
- Overrides are Python modules in overrides/{agent_name}/ with a check() function
- Loaded automatically based on BRAIN_AGENT_NAME env var
- Override results merged with standard LEP engine results
"""

import sys
import os
import importlib.util
from pathlib import Path
from typing import Optional, List
import re as _re

# Add modules to path
_HOOK_ROOT = os.environ.get("HOOK_ROOT")
if _HOOK_ROOT:
    HOOKS_ROOT = Path(_HOOK_ROOT)
else:
    _here = Path(__file__).resolve().parent
    if _here.parent.name == "handlers":
        HOOKS_ROOT = _here.parent.parent          # src 模式
    else:
        HOOKS_ROOT = _here.parent                  # deployed 模式

SERVICE_ROOT = HOOKS_ROOT
sys.path.insert(0, str(HOOKS_ROOT / "lep"))
sys.path.insert(0, str(HOOKS_ROOT / "utils"))
sys.path.insert(0, str(HOOKS_ROOT / "checkers" / "audit_logger"))

try:
    from engine import LepEngine
    from cache import get_lep_config
    from io_helper import load_json_input, output_block, output_warn, output_pass
    from logger import log_tool_use
    from result import CheckResult, CheckContext
except ImportError as e:
    print(f"Critical: Failed to import required modules: {e}", file=sys.stderr)
    print(f"sys.path: {sys.path}", file=sys.stderr)
    sys.exit(0)  # Fail-safe: allow operation on import error


# Global engine instance (lazy-initialized)
_ENGINE = None

_SCRIPT_EXEC_PATTERNS = [
    _re.compile(r'python3?\s+(\/\S+\.py)'),
    _re.compile(r'bash\s+(\/\S+\.sh)'),
    _re.compile(r'sh\s+(\/\S+\.sh)'),
]

# Only scan temp directories to avoid blocking system tools
_SCAN_ONLY_PREFIXES = [
    '/tmp/',
    '/var/tmp/',
    '/dev/shm/',
]

# File operation commands that can write to arbitrary destinations
_FILE_OP_PATTERNS = [
    # cp src dst, cp -r src dst
    _re.compile(r'\bcp\s+(?:-\S+\s+)*\S+\s+(\/\S+)'),
    # mv src dst
    _re.compile(r'\bmv\s+(?:-\S+\s+)*\S+\s+(\/\S+)'),
    # cat > /path or cat >> /path
    _re.compile(r'\bcat\b.*?[>]{1,2}\s*(\/\S+)'),
    # tee /path or tee -a /path
    _re.compile(r'\btee\s+(?:-\S+\s+)*(\/\S+)'),
    # dd ... of=/path
    _re.compile(r'\bdd\b.*?\bof=(\/\S+)'),
    # sed -i ... /path
    _re.compile(r'\bsed\s+(?:-\S+\s+)*(?:\'[^\']*\'|"[^"]*")\s+(\/\S+)'),
    # install src dst
    _re.compile(r'\binstall\s+(?:-\S+\s+)*\S+\s+(\/\S+)'),
    # rsync src dst
    _re.compile(r'\brsync\s+(?:-\S+\s+)*\S+\s+(\/\S+)'),
]


def _check_file_op_destination(command: str):
    """Check file operation commands for protected destination paths.

    Returns: (is_blocked, command_name, matched_prefix)
    """
    for pattern in _FILE_OP_PATTERNS:
        for m in pattern.finditer(command):
            dest = m.group(1).rstrip(';').rstrip("'").rstrip('"')
            # Expand /xkagent_infra prefix if needed
            for prefix in _PROTECTED_PREFIXES:
                full_prefix = prefix
                xka_prefix = '/xkagent_infra' + prefix
                if dest.startswith(full_prefix) or dest.startswith(xka_prefix):
                    cmd_name = command.split()[0] if command.split() else 'unknown'
                    return True, cmd_name, prefix
    return False, '', ''

_PROTECTED_PREFIXES = [
    '/brain/base/spec/core/',
    '/brain/base/workflow/',
    '/brain/INIT.yaml',
    '/brain/base/spec/',
]


def _check_script_content(command: str):
    """Check script content for protected paths.

    Returns: (is_blocked, script_path, matched_prefix)
    """
    for pattern in _SCRIPT_EXEC_PATTERNS:
        m = pattern.search(command)
        if m:
            script_path = m.group(1)
            if not any(script_path.startswith(p) for p in _SCAN_ONLY_PREFIXES):
                continue
            try:
                with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                for prefix in _PROTECTED_PREFIXES:
                    if prefix in content:
                        return True, script_path, prefix
            except (IOError, OSError):
                pass
    return False, '', ''


def get_engine():
    """Get or create the global LepEngine instance"""
    global _ENGINE

    if _ENGINE is None:
        try:
            lep_config = get_lep_config()
            _ENGINE = LepEngine(lep_config, SERVICE_ROOT)
        except Exception as e:
            print(f"Warning: Failed to initialize LepEngine: {e}", file=sys.stderr)
            return None

    return _ENGINE


# ─── Agent Overrides ─────────────────────────────────────────────────

_OVERRIDES_LOADED = False
_OVERRIDE_MODULES = []


def _load_overrides():
    """Load agent-specific override checkers based on BRAIN_AGENT_NAME.

    Scans overrides/{agent_name}/ for Python modules with a check() function.
    Each module should have:
      - check(context: CheckContext) -> CheckResult
      - OVERRIDE_META dict (optional, for trigger filtering)
    """
    global _OVERRIDES_LOADED, _OVERRIDE_MODULES

    if _OVERRIDES_LOADED:
        return _OVERRIDE_MODULES

    _OVERRIDES_LOADED = True
    agent_name = os.environ.get("BRAIN_AGENT_NAME", "")
    if not agent_name:
        return _OVERRIDE_MODULES

    overrides_dir = HOOKS_ROOT / "overrides" / agent_name
    if not overrides_dir.is_dir():
        return _OVERRIDE_MODULES

    for py_file in sorted(overrides_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"override_{agent_name}_{py_file.stem}", str(py_file)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "check") and callable(module.check):
                _OVERRIDE_MODULES.append(module)
        except Exception as e:
            print(f"Warning: Failed to load override {py_file}: {e}", file=sys.stderr)

    if _OVERRIDE_MODULES:
        names = [m.__name__.split("_")[-1] for m in _OVERRIDE_MODULES]
        print(f"Loaded {len(_OVERRIDE_MODULES)} override(s) for {agent_name}: {names}",
              file=sys.stderr)

    return _OVERRIDE_MODULES


def _run_overrides(tool_name: str, tool_input: dict) -> Optional[CheckResult]:
    """Run agent-specific override checkers.

    Returns first block or first warn, or None if all pass.
    """
    overrides = _load_overrides()
    if not overrides:
        return None

    context = CheckContext(
        tool_name=tool_name,
        tool_input=tool_input,
        gate_id="",
        enforcement={},
        file_path=tool_input.get("file_path", ""),
        command=tool_input.get("command", ""),
    )

    warnings = []

    for module in overrides:
        try:
            result = module.check(context)

            if result.is_block:
                return result
            if result.is_warn:
                warnings.append(result)
        except Exception as e:
            gate_id = getattr(module, "OVERRIDE_META", {}).get("gate_id", module.__name__)
            print(f"Warning: Override {gate_id} error: {e}", file=sys.stderr)

    return warnings[0] if warnings else None


# ─── Handlers ────────────────────────────────────────────────────────

def handle_pre_tool_use():
    """PreToolUse: YAML-driven validation + agent overrides

    Flow:
        1. Load JSON input from stdin
        2. Run agent-specific overrides (collect warn, stop on block)
        3. Run standard LepEngine checks
        4. Merge results: block > warn > pass
        5. Log audit trail
    """
    try:
        # 1. Load input
        data = load_json_input()
        tool_name = data.get("tool_name", data.get("toolName", ""))
        tool_input = data.get("tool_input", data.get("toolInput", {}))

        # 0. Script content security check (prevent /tmp/xxx.py bypass)
        if tool_name in ("Bash",):
            command = tool_input.get("command", "")
            blocked, script_path, matched = _check_script_content(command)
            if blocked:
                log_tool_use("PreToolUse", tool_name, tool_input,
                            blocked=True, gate="G-SCOP-SCRIPT")
                output_block("PreToolUse",
                    f"BLOCK: 脚本内容包含受保护路径 (G-SCOP)\n"
                    f"脚本: {script_path}\n"
                    f"包含受保护路径: {matched}\n"
                    f"禁止通过脚本间接修改受保护路径。"
                )
                sys.exit(0)

            # 0b. File operation destination check (prevent cp/mv bypass)
            blocked, cmd_name, matched = _check_file_op_destination(command)
            if blocked:
                log_tool_use("PreToolUse", tool_name, tool_input,
                            blocked=True, gate="G-SCOP-FILEOP")
                output_block("PreToolUse",
                    f"BLOCK: 文件操作目标为受保护路径 (G-SCOP)\n"
                    f"命令: {cmd_name}\n"
                    f"目标包含受保护路径: {matched}\n"
                    f"禁止通过 cp/mv/tee/dd 等命令直接写入受保护路径。"
                )
                sys.exit(0)

        # 2. Run overrides first
        override_result = _run_overrides(tool_name, tool_input)

        # Override block → immediate stop
        if override_result and override_result.is_block:
            log_tool_use("PreToolUse", tool_name, tool_input,
                        blocked=True, gate=override_result.gate_id)
            output_block("PreToolUse", override_result.message)
            sys.exit(0)

        # 3. Run standard engine
        engine = get_engine()

        if engine is None:
            print("Warning: LepEngine not available, allowing operation", file=sys.stderr)
            if override_result and override_result.is_warn:
                log_tool_use("PreToolUse", tool_name, tool_input,
                            warned=True, gate=override_result.gate_id)
                output_warn("PreToolUse", override_result.message)
            else:
                log_tool_use("PreToolUse", tool_name, tool_input,
                            warned=True, gate="ENGINE_INIT_FAILED")
                output_pass("PreToolUse")
            sys.exit(0)

        engine_result = engine.check(tool_name, tool_input)

        # 4. Merge results: engine block > override warn > engine warn > pass
        if engine_result.is_block:
            # Engine block wins, but prepend override warn to message if present
            msg = engine_result.message
            if override_result and override_result.is_warn:
                msg = override_result.message + "\n\n" + msg
            log_tool_use("PreToolUse", tool_name, tool_input,
                        blocked=True, gate=engine_result.gate_id)
            output_block("PreToolUse", msg)
            sys.exit(0)

        if override_result and override_result.is_warn:
            # Override warn (engine passed or also warned)
            msg = override_result.message
            if engine_result.is_warn:
                msg = msg + "\n\n" + engine_result.message
            log_tool_use("PreToolUse", tool_name, tool_input,
                        warned=True, gate=override_result.gate_id)
            output_warn("PreToolUse", msg)

        elif engine_result.is_warn:
            log_tool_use("PreToolUse", tool_name, tool_input,
                        warned=True, gate=engine_result.gate_id)
            output_warn("PreToolUse", engine_result.message)

        # 5. Log and pass
        log_tool_use("PreToolUse", tool_name, tool_input)
        output_pass("PreToolUse")
        sys.exit(0)

    except Exception as e:
        print(f"PreToolUse handler error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)


def handle_post_tool_use():
    """PostToolUse: Audit logging only"""
    try:
        data = load_json_input()
        tool_name = data.get("tool_name", data.get("toolName", ""))
        tool_input = data.get("tool_input", data.get("toolInput", {}))

        log_tool_use("PostToolUse", tool_name, tool_input)
        output_pass("PostToolUse")
        sys.exit(0)

    except Exception as e:
        print(f"PostToolUse handler error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    if "pre_tool_use" in sys.argv[0]:
        handle_pre_tool_use()
    elif "post_tool_use" in sys.argv[0]:
        handle_post_tool_use()
    else:
        handle_pre_tool_use()
