#!/usr/bin/env python3
"""LEP Engine - YAML-Driven Gate Enforcement"""

from pathlib import Path
from typing import List, Optional, Dict, Any
import os
import re
import sys
import fnmatch

from lep import load_lep, LepConfig
from result import CheckResult, GateMatch, CheckContext, CheckStatus
from checkers import (
    BaseChecker,
    InlineChecker,
    BinaryChecker,
    PathChecker,
    FileOrgChecker,
    NawpChecker,
    IpcTargetChecker,
    ApprovalDelegationChecker,
    DeferChecker,
    VerificationChecker,
)


# Priority order for gate execution
PRIORITY_ORDER = {
    'CRITICAL': 0,
    'HIGH': 1,
    'MEDIUM': 2,
    'LOW': 3,
}


class LepEngine:
    """YAML-driven LEP enforcement engine"""

    def __init__(self, lep_config: Optional[LepConfig] = None, hook_root: Optional[Path] = None):
        # 优先使用环境变量 HOOK_ROOT
        if hook_root is None:
            hook_root = os.environ.get("HOOK_ROOT")
        self.config = lep_config or load_lep()
        self.hook_root = Path(hook_root) if hook_root else Path("/brain/infrastructure/service/agent_abilities")
        self._checker_registry: Dict[str, BaseChecker] = {}
        self._build_checker_registry()

    def _build_checker_registry(self):
        """Build checker instances from gate configs"""
        for gate_id, gate_spec in self.config.gates.items():
            enforcement = gate_spec.get('enforcement', {})

            if not enforcement:
                continue

            method = enforcement.get('method', 'inline')

            try:
                if method == 'c_binary':
                    # C binary checker
                    binary_name = enforcement.get('binary', 'lep_check')
                    # HOOK_ROOT 已指向发布目录，lep 直接在 HOOK_ROOT 下
                    binary_path = str(self.hook_root / "lep" / binary_name)
                    check_type = enforcement.get('check_type', 'protected')
                    self._checker_registry[gate_id] = BinaryChecker(binary_path, check_type)

                elif method == 'python_checker':
                    # Python checker wrapper
                    checker_name = enforcement.get('checker', '').lower()

                    if 'path' in checker_name:
                        self._checker_registry[gate_id] = PathChecker(self.hook_root)
                    elif 'file_org' in checker_name:
                        self._checker_registry[gate_id] = FileOrgChecker(self.hook_root)

                elif method in ['python_inline', 'inline']:
                    # Inline regex checker
                    patterns = enforcement.get('patterns', {})
                    if patterns:
                        self._checker_registry[gate_id] = InlineChecker(patterns)

                elif method == 'plan_mode_check':
                    self._checker_registry[gate_id] = NawpChecker()

                elif method == 'daemon_validation':
                    self._checker_registry[gate_id] = IpcTargetChecker()

                elif method == 'message_routing_validation':
                    self._checker_registry[gate_id] = ApprovalDelegationChecker()

                elif method == 'message_content_validation':
                    self._checker_registry[gate_id] = DeferChecker()

                elif method == 'test_runner':
                    self._checker_registry[gate_id] = VerificationChecker()

            except Exception as e:
                print(f"Warning: Failed to create checker for {gate_id}: {e}", file=sys.stderr)

    def _match_gates(self, tool_name: str, tool_input: Dict[str, Any]) -> List[GateMatch]:
        """Find gates that apply to this operation"""
        matches = []
        file_path = tool_input.get('file_path', '')
        command = tool_input.get('command', '')

        for gate_id, gate_spec in self.config.gates.items():
            enforcement = gate_spec.get('enforcement', {})

            if not enforcement:
                continue

            # Check stage
            # Special methods run in pre_tool_use context regardless of declared stage
            method = enforcement.get('method', '')
            virtual_pre_tool_use_methods = {
                'plan_mode_check', 'daemon_validation',
                'message_routing_validation', 'message_content_validation', 'test_runner',
            }
            stage = enforcement.get('stage', '')
            if stage and stage != 'pre_tool_use' and method not in virtual_pre_tool_use_methods:
                continue

            # Check triggers
            triggers = enforcement.get('triggers', {})

            # 1. Check tool triggers
            tool_list = triggers.get('tools', [])

            # Also handle mcp_tool trigger (flexible: check substring match)
            mcp_tool = triggers.get('mcp_tool', '')
            if mcp_tool and mcp_tool.lower() in tool_name.lower():
                pass  # MCP tool matched — continue to checker
            elif tool_list and tool_name not in tool_list:
                continue

            # 2. Check path patterns (if file_path exists)
            path_patterns = triggers.get('patterns', [])
            if path_patterns and file_path:
                if not self._matches_any_pattern(file_path, path_patterns):
                    continue

            # 3. Check command patterns (if command exists)
            cmd_patterns = triggers.get('commands', [])
            if cmd_patterns and command:
                if not self._matches_any_command(command, cmd_patterns):
                    continue

            # 4. Check additional pattern groups
            pattern_groups = triggers.get('patterns', {})
            if isinstance(pattern_groups, dict) and (command or file_path):
                matched = False
                for group_name, group_patterns in pattern_groups.items():
                    if not isinstance(group_patterns, list):
                        continue

                    for pattern in group_patterns:
                        if isinstance(pattern, str):
                            # Simple pattern
                            try:
                                if command and re.search(pattern, command, re.IGNORECASE):
                                    matched = True
                                    break
                            except re.error:
                                # Invalid regex - skip this pattern
                                continue
                        elif isinstance(pattern, dict):
                            # Pattern with metadata
                            pattern_str = pattern.get('pattern', '')
                            try:
                                if command and re.search(pattern_str, command, re.IGNORECASE):
                                    matched = True
                                    break
                            except re.error:
                                # Invalid regex - skip this pattern
                                continue

                    if matched:
                        break

                # If has pattern groups but nothing matched, skip this gate
                if pattern_groups and not matched and not (path_patterns or cmd_patterns):
                    continue

            # Gate matches - add to list
            priority = enforcement.get('priority', 'MEDIUM')
            checker_type = enforcement.get('method', 'inline')

            matches.append(GateMatch(
                gate_id=gate_id,
                gate_spec=gate_spec,
                enforcement=enforcement,
                priority=priority,
                checker_type=checker_type
            ))

        # Sort by priority
        matches.sort(key=lambda m: PRIORITY_ORDER.get(m.priority, 99))

        return matches

    def _matches_any_pattern(self, path: str, patterns: list) -> bool:
        """Check if path matches any pattern (using fnmatch)"""
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    def _matches_any_command(self, command: str, patterns: list) -> bool:
        """Check if command matches any pattern (using regex)"""
        for pattern in patterns:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    return True
            except re.error:
                # Invalid regex - skip
                continue
        return False

    def check(self, tool_name: str, tool_input: Dict[str, Any]) -> CheckResult:
        """Execute all applicable gate checks

        Args:
            tool_name: Name of the tool being used (Write, Edit, Bash, etc.)
            tool_input: Tool input parameters (file_path, command, etc.)

        Returns:
            CheckResult: First blocking result, or first warning, or pass
        """
        # 1. Match applicable gates
        gate_matches = self._match_gates(tool_name, tool_input)

        if not gate_matches:
            return CheckResult.pass_check()

        # 2. Build context
        context = CheckContext(
            tool_name=tool_name,
            tool_input=tool_input,
            gate_id="",
            enforcement={},
            file_path=tool_input.get('file_path', ''),
            command=tool_input.get('command', '')
        )

        # 3. Execute checks
        warnings: List[CheckResult] = []

        for gate_match in gate_matches:
            checker = self._checker_registry.get(gate_match.gate_id)

            if not checker:
                # No checker registered for this gate - skip
                continue

            # Update context
            context.gate_id = gate_match.gate_id
            context.enforcement = gate_match.enforcement

            try:
                result = checker.check(context)

                # First block wins - stop immediately
                if result.is_block:
                    return result

                # Collect warnings
                if result.is_warn:
                    warnings.append(result)

            except Exception as e:
                print(f"Warning: Checker error in {gate_match.gate_id}: {e}", file=sys.stderr)
                # Continue to next gate on error

        # 4. Return first warning or pass
        if warnings:
            return warnings[0]

        return CheckResult.pass_check()


__all__ = [
    "LepEngine",
    "PRIORITY_ORDER",
]
