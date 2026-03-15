#!/usr/bin/env python3
"""Role-based scope enforcement for LEP Engine.

Reads role context from environment variables (injected by agentctl):
  - BRAIN_AGENT_NAME:  agent name
  - BRAIN_AGENT_ROLE:  role (pmo, architect, dev, devops, qa, ...)
  - BRAIN_AGENT_GROUP: group (brain_system, xkquant, ...)
  - BRAIN_SCOPE_PATH:  base scope path (/brain/groups/org/{group})
  - BRAIN_ENABLED_LEP_PROFILES:  comma-separated LEP profile overlays

Loads role-specific gates from:
  hooks/rules/roles/{role}/gates.yaml
Loads LEP profile overlays from:
  hooks/rules/profiles/{profile}/gates.yaml

Provides scope checking: is a given file_path writable for this role?
"""

from __future__ import annotations

import os
import re
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


RULES_DIR = Path(__file__).parent.parent.parent / "rules" / "roles"
PROFILES_DIR = Path(__file__).parent.parent.parent / "rules" / "profiles"


@dataclass(frozen=True)
class RoleContext:
    """Agent role context from environment."""
    agent_name: str
    role: str
    group: str
    scope_path: str

    @classmethod
    def from_env(cls) -> "RoleContext":
        return cls(
            agent_name=os.environ.get("BRAIN_AGENT_NAME", ""),
            role=os.environ.get("BRAIN_AGENT_ROLE", "default"),
            group=os.environ.get("BRAIN_AGENT_GROUP", ""),
            scope_path=os.environ.get("BRAIN_SCOPE_PATH", "/brain"),
        )


@dataclass
class RoleScopeRules:
    """Scope rules for a specific role."""
    role: str
    allowed_write: list[str] = field(default_factory=list)
    denied_write: list[str] = field(default_factory=list)
    gate_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra_protected: list[str] = field(default_factory=list)

    @classmethod
    def _load_rules_file(
        cls,
        rules_file: Path,
        *,
        role: str,
        group: str = "",
        agent_name: str = "",
    ) -> "RoleScopeRules":
        try:
            with open(rules_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return cls(role=role)

        scope = data.get("scope", {})

        def expand(paths: list) -> list[str]:
            """Expand {group}/{agent} placeholders in paths."""
            result = []
            for p in (paths or []):
                if isinstance(p, str):
                    expanded = p
                    if group:
                        expanded = expanded.replace("{group}", group)
                        expanded = expanded.replace(
                            f"/agents/agent_{group}_",
                            f"/agents/agent-{group}_",
                        )
                    if agent_name:
                        expanded = expanded.replace("{agent}", agent_name)
                    if group == "brain":
                        expanded = expanded.replace(
                            "/xkagent_infra/groups/brain/agents/",
                            "/xkagent_infra/brain/agents/",
                        )
                    result.append(expanded)
            return result

        return cls(
            role=role,
            allowed_write=expand(scope.get("allowed_write", [])),
            denied_write=expand(scope.get("denied_write", [])),
            gate_overrides=data.get("gate_overrides", {}),
            extra_protected=expand(scope.get("extra_protected", [])),
        )

    @classmethod
    def merge(cls, base: "RoleScopeRules", overlay: "RoleScopeRules") -> "RoleScopeRules":
        def dedupe(items: list[str]) -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            for item in items:
                if not item or item in seen:
                    continue
                seen.add(item)
                result.append(item)
            return result

        merged_overrides = dict(base.gate_overrides)
        merged_overrides.update(overlay.gate_overrides or {})
        return cls(
            role=base.role,
            allowed_write=dedupe([*(base.allowed_write or []), *(overlay.allowed_write or [])]),
            denied_write=dedupe([*(base.denied_write or []), *(overlay.denied_write or [])]),
            gate_overrides=merged_overrides,
            extra_protected=dedupe([*(base.extra_protected or []), *(overlay.extra_protected or [])]),
        )

    @classmethod
    def load(
        cls,
        role: str,
        group: str = "",
        *,
        agent_name: str = "",
        profiles: list[str] | None = None,
    ) -> "RoleScopeRules":
        """Load role scope rules and merge optional LEP profile overlays."""
        rules_file = RULES_DIR / role / "gates.yaml"
        base = cls(role=role)
        if rules_file.exists():
            base = cls._load_rules_file(rules_file, role=role, group=group, agent_name=agent_name)

        for profile in profiles or []:
            profile_name = str(profile).strip()
            if not profile_name:
                continue
            profile_file = PROFILES_DIR / profile_name / "gates.yaml"
            if not profile_file.exists():
                continue
            overlay = cls._load_rules_file(profile_file, role=role, group=group, agent_name=agent_name)
            base = cls.merge(base, overlay)

        return base


def check_write_scope(
    file_path: str,
    rules: RoleScopeRules,
    context: RoleContext,
) -> tuple[bool, str]:
    """Check if a file path is writable for the given role.

    Returns:
        (allowed, reason) - True if write is allowed, False with reason if denied.

    Logic:
        1. If denied_write matches -> BLOCK
        2. If allowed_write is defined and path matches -> ALLOW
        3. If allowed_write is defined but no match -> BLOCK
        4. If no allowed_write rules -> ALLOW (permissive default)
    """
    if not file_path or not rules:
        return True, ""

    # 1. Check explicit denials first
    for pattern in rules.denied_write:
        if _matches(file_path, pattern):
            return False, (
                f"Role '{rules.role}' cannot write to {file_path}\n"
                f"Denied by pattern: {pattern}\n"
                f"Agent: {context.agent_name} | Group: {context.group}"
            )

    # 2. If allowed_write is defined, check whitelist
    if rules.allowed_write:
        for pattern in rules.allowed_write:
            if _matches(file_path, pattern):
                return True, ""
        # No match in whitelist
        return False, (
            f"Role '{rules.role}' can only write to allowed paths\n"
            f"File: {file_path}\n"
            f"Allowed: {', '.join(rules.allowed_write[:3])}...\n"
            f"Agent: {context.agent_name} | Group: {context.group}"
        )

    # 3. No rules defined -> permissive
    return True, ""


def check_bash_scope(
    command: str,
    rules: RoleScopeRules,
    context: RoleContext,
) -> tuple[bool, str]:
    """Check if a bash command is allowed for the given role.

    Extracts file paths from common write commands and checks scope.
    """
    if not command or not rules:
        return True, ""

    # Extract target paths from write commands
    write_patterns = [
        # echo/cat redirect: echo "x" > /path or cat > /path
        (r'>\s*(/\S+)', "redirect"),
        # cp/mv destination: cp src /dest or mv src /dest
        (r'(?:cp|mv)\s+\S+\s+(/\S+)', "copy/move destination"),
        # touch: touch /path
        (r'touch\s+(/\S+)', "touch"),
        # mkdir: mkdir /path
        (r'mkdir\s+(?:-p\s+)?(/\S+)', "mkdir"),
        # tee: ... | tee /path
        (r'tee\s+(?:-a\s+)?(/\S+)', "tee"),
    ]

    for pattern, op_type in write_patterns:
        match = re.search(pattern, command)
        if match:
            target_path = match.group(1)
            allowed, reason = check_write_scope(target_path, rules, context)
            if not allowed:
                return False, f"Bash {op_type} blocked: {reason}"

    return True, ""


def _matches(path: str, pattern: str) -> bool:
    """Match path against a glob/fnmatch pattern.

    Supports:
      - /brain/base/** → matches anything under /brain/base/
      - /brain/groups/**/projects/** → matches any nesting depth
      - /brain/groups/org/{group}/** → already expanded

    Key: "**" matches zero or more path segments (including zero).
    """
    # Strategy 1: If pattern ends with /**, check starts_with on the base
    if pattern.endswith("/**"):
        base = pattern[:-3]  # strip /**
        if path.startswith(base + "/") or path == base:
            return True

    # Strategy 2: If pattern contains internal /**, expand to multiple prefix checks
    # e.g., /brain/groups/org/foo/**/projects/** becomes:
    #   - /brain/groups/org/foo/projects/  (** = zero segments)
    #   - /brain/groups/org/foo/*/projects/ (** = one segment)
    #   ... covered by fnmatch with * matching /
    if "/**/" in pattern:
        # Replace /**/ with / for zero-depth match
        zero_depth = pattern.replace("/**/", "/")
        if _matches(path, zero_depth):
            return True

    # Strategy 3: fnmatch with ** → * (fnmatch * matches / on posix)
    fn_pattern = pattern.replace("**", "*")
    if fnmatch.fnmatch(path, fn_pattern):
        return True

    # Strategy 4: Simple prefix check for directory patterns
    base = pattern.rstrip("*").rstrip("/")
    if base and not "*" in base and path.startswith(base + "/"):
        return True

    return False


# Module-level cache
_ROLE_CONTEXT: RoleContext | None = None
_ROLE_RULES: RoleScopeRules | None = None


def get_role_context() -> RoleContext:
    """Get cached role context."""
    global _ROLE_CONTEXT
    if _ROLE_CONTEXT is None:
        _ROLE_CONTEXT = RoleContext.from_env()
    return _ROLE_CONTEXT


def get_role_rules() -> RoleScopeRules:
    """Get cached role scope rules."""
    global _ROLE_RULES
    if _ROLE_RULES is None:
        ctx = get_role_context()
        raw_profiles = os.environ.get("BRAIN_ENABLED_LEP_PROFILES", "")
        profiles = [item.strip() for item in raw_profiles.split(",") if item.strip()]
        _ROLE_RULES = RoleScopeRules.load(
            ctx.role,
            ctx.group,
            agent_name=ctx.agent_name,
            profiles=profiles,
        )
    return _ROLE_RULES


__all__ = [
    "RoleContext",
    "RoleScopeRules",
    "check_write_scope",
    "check_bash_scope",
    "get_role_context",
    "get_role_rules",
]
