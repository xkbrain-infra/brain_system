#!/usr/bin/env python3
"""LEP Engine - Checker Implementations"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import re
import subprocess
import sys
import fnmatch
import yaml

from result import CheckResult, CheckContext


class BaseChecker(ABC):
    """Base class for all checkers"""

    @abstractmethod
    def check(self, context: CheckContext) -> CheckResult:
        """Execute the check and return result"""
        pass

    def format_message(self, template: str, **kwargs) -> str:
        """Format message template with variables"""
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError) as e:
            print(f"Warning: Template formatting error: {e}", file=sys.stderr)
            return template


class InlineChecker(BaseChecker):
    """Pattern matching checker using regex"""

    def __init__(self, patterns: Dict[str, List[Dict[str, str]]]):
        self.patterns = patterns
        self._compiled = self._compile_patterns(patterns)

    def _compile_patterns(self, patterns: Dict[str, List[Dict[str, str]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Precompile regex patterns for performance"""
        compiled = {}

        for key, pattern_list in patterns.items():
            compiled[key] = []

            if not isinstance(pattern_list, list):
                continue

            for item in pattern_list:
                if not isinstance(item, dict):
                    continue

                pattern_str = item.get('pattern')
                if not pattern_str:
                    continue

                try:
                    compiled[key].append({
                        'regex': re.compile(pattern_str),
                        'message': item.get('message', ''),
                        'suggestion': item.get('suggestion', ''),
                        'priority': item.get('priority'),
                        'action': item.get('action'),
                    })
                except re.error as e:
                    print(f"Warning: Invalid regex pattern '{pattern_str}': {e}", file=sys.stderr)

        return compiled

    def check(self, context: CheckContext) -> CheckResult:
        """Check patterns against command/path"""
        command = context.command
        file_path = context.file_path

        # Check command patterns
        if command:
            for pattern_group in self._compiled.values():
                for pattern_info in pattern_group:
                    if pattern_info['regex'].search(command):
                        # Build message from template
                        msg_template = context.enforcement.get('warn_message') or context.enforcement.get('block_message', '')
                        message = self.format_message(
                            msg_template,
                            command=command,
                            file_path=file_path,
                            operation=context.tool_name,
                            message=pattern_info['message'],
                            suggestion=pattern_info['suggestion']
                        )

                        # Determine block vs warn: per-pattern priority/action > enforcement-level
                        priority = pattern_info.get('priority') or context.enforcement.get('priority', 'MEDIUM')
                        action = pattern_info.get('action') or ''
                        if action == 'block' or priority in ['CRITICAL', 'HIGH']:
                            return CheckResult.block(context.gate_id, message, priority)
                        else:
                            return CheckResult.warn(context.gate_id, message, priority)

        # Check file path patterns
        if file_path:
            for pattern_group in self._compiled.values():
                for pattern_info in pattern_group:
                    if pattern_info['regex'].search(file_path):
                        msg_template = context.enforcement.get('warn_message') or context.enforcement.get('block_message', '')
                        message = self.format_message(
                            msg_template,
                            file_path=file_path,
                            command=command,
                            operation=context.tool_name,
                            message=pattern_info['message'],
                            suggestion=pattern_info['suggestion']
                        )

                        priority = pattern_info.get('priority') or context.enforcement.get('priority', 'MEDIUM')
                        action = pattern_info.get('action') or ''
                        if action == 'block' or priority in ['CRITICAL', 'HIGH']:
                            return CheckResult.block(context.gate_id, message, priority)
                        else:
                            return CheckResult.warn(context.gate_id, message, priority)

        return CheckResult.pass_check()


class BinaryChecker(BaseChecker):
    """Wrapper for lep_check C binary"""

    def __init__(self, binary_path: str, check_type: str):
        self.binary_path = binary_path
        self.check_type = check_type

    def check(self, context: CheckContext) -> CheckResult:
        """Execute lep_check binary.

        Only checks file_path for path-protection gates.
        Never passes raw command strings to lep_check — command strings
        contain executable paths (e.g. agentctl) that would false-positive
        against protected prefix matching.
        """
        target = context.file_path

        if not target:
            return CheckResult.pass_check()

        try:
            result = subprocess.run(
                [self.binary_path, self.check_type, target],
                capture_output=True,
                text=True,
                timeout=1,
                check=False
            )

            if result.returncode == 1:
                # Block
                msg_template = context.enforcement.get('block_message', result.stderr)
                message = self.format_message(
                    msg_template,
                    file_path=context.file_path,
                    command=context.command
                )
                return CheckResult.block(context.gate_id, message, "CRITICAL")

            elif result.returncode == 2:
                # Warn
                msg_template = context.enforcement.get('warn_message', result.stderr)
                message = self.format_message(
                    msg_template,
                    file_path=context.file_path,
                    command=context.command
                )
                return CheckResult.warn(context.gate_id, message)

            return CheckResult.pass_check()

        except subprocess.TimeoutExpired:
            print(f"Warning: lep_check timeout for {target}", file=sys.stderr)
            return CheckResult.pass_check()
        except Exception as e:
            print(f"Warning: lep_check error: {e}", file=sys.stderr)
            return CheckResult.pass_check()


class PathChecker(BaseChecker):
    """Wrapper for existing path_checker"""

    def __init__(self, hook_root: Path = None):
        # 优先使用环境变量 HOOK_ROOT
        if hook_root is None:
            hook_root = os.environ.get("HOOK_ROOT")
        self.hook_root = Path(hook_root) if hook_root else Path("/brain/infrastructure/service/agent_abilities")

        # Import path_checker
        checker_path = self.hook_root / "checkers" / "path_checker"
        sys.path.insert(0, str(checker_path))

        try:
            from checker import check_spec_path
            self.check_spec_path = check_spec_path
        except ImportError as e:
            print(f"Warning: Failed to import path_checker: {e}", file=sys.stderr)
            self.check_spec_path = None

        # Fallback rules file
        self.rules_yaml = self.hook_root / "rules" / "spec_path.yaml"

    def check(self, context: CheckContext) -> CheckResult:
        """Check SPEC path validity"""
        if not self.check_spec_path:
            return CheckResult.pass_check()

        file_path = context.file_path
        if not file_path:
            return CheckResult.pass_check()

        try:
            is_valid, error_msg = self.check_spec_path(file_path, self.rules_yaml)

            if not is_valid:
                return CheckResult.block(context.gate_id, error_msg, "CRITICAL")

            return CheckResult.pass_check()

        except Exception as e:
            print(f"Warning: path_checker error: {e}", file=sys.stderr)
            return CheckResult.pass_check()


class FileOrgChecker(BaseChecker):
    """Wrapper for existing file_org_checker"""

    def __init__(self, hook_root: Path = None):
        # 优先使用环境变量 HOOK_ROOT
        if hook_root is None:
            hook_root = os.environ.get("HOOK_ROOT")
        self.hook_root = Path(hook_root) if hook_root else Path("/brain/infrastructure/service/agent_abilities")

        # Import file_org_checker using importlib to avoid naming conflicts
        try:
            import importlib.util
            checker_path = self.hook_root / "checkers" / "file_org_checker" / "checker.py"
            spec = importlib.util.spec_from_file_location("file_org_checker_module", str(checker_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.check_file_organization = module.check_file_organization
        except Exception as e:
            print(f"Warning: Failed to import file_org_checker: {e}", file=sys.stderr)
            self.check_file_organization = None

    def check(self, context: CheckContext) -> CheckResult:
        """Check file organization compliance"""
        if not self.check_file_organization:
            return CheckResult.pass_check()

        file_path = context.file_path
        if not file_path:
            return CheckResult.pass_check()

        try:
            is_valid, error_msg = self.check_file_organization(file_path)

            if not is_valid:
                # Use custom message template if provided
                msg_template = context.enforcement.get('block_message', error_msg)
                message = self.format_message(
                    msg_template,
                    file_path=file_path,
                    reason=error_msg
                )
                return CheckResult.block(context.gate_id, message, "HIGH")

            return CheckResult.pass_check()

        except Exception as e:
            print(f"Warning: file_org_checker error: {e}", file=sys.stderr)
            return CheckResult.pass_check()


class NawpChecker(BaseChecker):
    """G-GATE-NAWP: Warn when writing to protected areas without a plan file."""

    PROTECTED_AREAS = [
        "/brain/base/spec/**",
        "/brain/base/workflow/**",
        "/brain/infrastructure/service/**",
    ]
    EXCEPTIONS = [
        "/brain/**/memory/**",
        "/xkagent_infra/runtime/tmp/**",
        "/xkagent_infra/runtime/logs/**",
    ]
    PLAN_DIR = Path("/root/.claude/plans/")

    def _glob_match(self, path: str, pattern: str) -> bool:
        """Match path against a glob pattern supporting ** as prefix wildcard."""
        # Convert /foo/bar/** to prefix match /foo/bar/
        if pattern.endswith("/**"):
            return path.startswith(pattern[:-3] + "/") or path == pattern[:-3]
        if pattern.endswith("/**/"):
            return path.startswith(pattern[:-4] + "/")
        # For patterns with ** in the middle, convert to regex
        regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        return bool(re.match(regex + "$", path))

    def _is_protected(self, path: str) -> bool:
        for pattern in self.PROTECTED_AREAS:
            if self._glob_match(path, pattern):
                return True
        return False

    def _is_excepted(self, path: str) -> bool:
        for pattern in self.EXCEPTIONS:
            if self._glob_match(path, pattern):
                return True
        return False

    def _has_plan(self) -> bool:
        if not self.PLAN_DIR.exists():
            return False
        plans = list(self.PLAN_DIR.glob("*.yaml")) + list(self.PLAN_DIR.glob("*.md"))
        return len(plans) > 0

    def check(self, context: CheckContext) -> CheckResult:
        file_path = context.file_path
        if not file_path:
            return CheckResult.pass_check()
        if self._is_excepted(file_path):
            return CheckResult.pass_check()
        if not self._is_protected(file_path):
            return CheckResult.pass_check()
        if self._has_plan():
            return CheckResult.pass_check()

        msg = context.enforcement.get("warn_message", "").format(
            operation=context.tool_name, file_path=file_path
        )
        return CheckResult.warn(context.gate_id, msg or
            f"⚠️ G-NAWP: Writing to protected area '{file_path}' without a plan. "
            f"Use EnterPlanMode first.", "CRITICAL")


class IpcTargetChecker(BaseChecker):
    """G-GATE-IPC-TARGET: Block ipc_send if target agent not in registry."""

    REGISTRY_PATH = Path("/brain/infrastructure/config/agentctl/agents_registry.yaml")

    def _load_known_agents(self) -> List[str]:
        try:
            if not self.REGISTRY_PATH.exists():
                return []
            with open(self.REGISTRY_PATH) as f:
                data = yaml.safe_load(f)
            # Structure: groups: {group_name: [{name: agent_name, ...}, ...]}
            names = []
            for agent_list in data.get("groups", {}).values():
                if isinstance(agent_list, list):
                    for a in agent_list:
                        if isinstance(a, dict) and "name" in a:
                            names.append(a["name"])
            return names
        except Exception as e:
            print(f"Warning: IpcTargetChecker registry load error: {e}", file=sys.stderr)
            return []

    def check(self, context: CheckContext) -> CheckResult:
        tool_input = context.tool_input
        target = tool_input.get("to", tool_input.get("target", ""))
        if not target:
            return CheckResult.pass_check()

        known = self._load_known_agents()
        if not known:
            # Can't verify — fail open
            return CheckResult.pass_check()

        if target in known:
            return CheckResult.pass_check()

        available = ", ".join(sorted(known)[:10])
        if len(known) > 10:
            available += f" ... (+{len(known)-10} more)"

        msg = (
            f"🚫 G-IPC-TARGET: Target agent '{target}' not found in registry.\n"
            f"Available agents: {available}\n"
            f"Run ipc_list_agents() to see online agents."
        )
        return CheckResult.block(context.gate_id, msg, "CRITICAL")


class ApprovalDelegationChecker(BaseChecker):
    """G-GATE-APPROVAL-DELEGATION: Warn when AskUserQuestion is used instead of PMO."""

    def check(self, context: CheckContext) -> CheckResult:
        if context.tool_name != "AskUserQuestion":
            return CheckResult.pass_check()

        msg = context.enforcement.get("warn_message", "")
        return CheckResult.warn(context.gate_id, msg or
            "💡 G-APPROVAL-DELEGATION: Use ipc_send(to=PMO, APPROVAL_REQUEST) "
            "instead of AskUserQuestion.", "MEDIUM")


class DeferChecker(BaseChecker):
    """G-GATE-DEFER: Warn when written content contains defer keywords."""

    KEYWORDS = ["以后", "稍后", "待办", "TODO", "延迟", "将来", "下次"]

    def check(self, context: CheckContext) -> CheckResult:
        if context.tool_name not in ("Write", "Edit"):
            return CheckResult.pass_check()

        content = (
            context.tool_input.get("content", "") or
            context.tool_input.get("new_string", "")
        )
        if not content:
            return CheckResult.pass_check()

        for kw in self.KEYWORDS:
            if kw in content:
                msg = context.enforcement.get("warn_message", "").replace("{keyword}", kw)
                return CheckResult.warn(context.gate_id, msg or
                    f"💡 G-DEFER: Detected defer keyword '{kw}'. "
                    f"Send structured IPC message to PMO instead of just writing it.", "MEDIUM")

        return CheckResult.pass_check()


class VerificationChecker(BaseChecker):
    """G-GATE-VERIFICATION: Warn when git commit runs without prior test evidence."""

    def check(self, context: CheckContext) -> CheckResult:
        command = context.command
        if not command:
            return CheckResult.pass_check()

        # Detect git commit (but not --amend or other subcommands)
        if not re.search(r'\bgit\s+commit\b', command):
            return CheckResult.pass_check()

        # Skip if --no-verify is already used (user is intentional)
        if "--no-verify" in command:
            return CheckResult.pass_check()

        msg = context.enforcement.get("warn_message", "")
        return CheckResult.warn(context.gate_id, msg or
            "⚠️ G-VERIFICATION: Remember to run tests before committing.\n"
            "  make build && make test", "HIGH")


__all__ = [
    "BaseChecker",
    "InlineChecker",
    "BinaryChecker",
    "PathChecker",
    "FileOrgChecker",
    "NawpChecker",
    "IpcTargetChecker",
    "ApprovalDelegationChecker",
    "DeferChecker",
    "VerificationChecker",
]
