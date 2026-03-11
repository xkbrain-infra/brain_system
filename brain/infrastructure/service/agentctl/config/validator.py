from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    level: str  # error | warn
    message: str
    agent: str | None = None


def _as_str(v: Any) -> str:
    return str(v or "").strip()


def _collect_agents_from_groups(root: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect all agent dicts from the V2 groups: structure."""
    groups = root.get("groups", {})
    if not isinstance(groups, dict):
        return []
    agents: list[dict[str, Any]] = []
    for _group_name, group_agents in groups.items():
        if isinstance(group_agents, list):
            for a in group_agents:
                if isinstance(a, dict):
                    agents.append(a)
    return agents


def _has_runtime_manifest(agent: dict[str, Any]) -> bool:
    base = _as_str(agent.get("path") or agent.get("cwd"))
    if not base:
        return False
    return (Path(base) / ".brain" / "agent_runtime.json").exists()


def validate_agents_registry(cfg: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not isinstance(cfg, dict):
        return [ValidationIssue(level="error", message="agents_registry root must be a mapping")]

    # The full YAML has groups: at top level alongside agents_registry:
    # So search cfg directly for groups, and also check nested agents_registry if present
    root = cfg.get("agents_registry", {}) if "agents_registry" in cfg else cfg
    if not isinstance(root, dict):
        root = {}

    # V2: collect from groups: structure (top-level of cfg)
    agents = _collect_agents_from_groups(cfg)
    if not agents:
        # Also check inside agents_registry sub-key
        agents = _collect_agents_from_groups(root)

    # Fallback to V1 agents: list if groups yielded nothing
    if not agents:
        v1_agents = root.get("agents", [])
        if isinstance(v1_agents, list):
            agents = [a for a in v1_agents if isinstance(a, dict)]

    if not agents:
        issues.append(ValidationIssue(level="warn", message="no agents found in registry (checked groups: and agents:)"))
        return issues

    seen: set[str] = set()
    for a in agents:
        if not isinstance(a, dict):
            issues.append(ValidationIssue(level="warn", message="agents_registry agent item is not a mapping"))
            continue

        name = _as_str(a.get("name"))
        if not name:
            issues.append(ValidationIssue(level="error", message="agent missing name"))
            continue
        if name in seen:
            issues.append(ValidationIssue(level="error", message="duplicate agent name", agent=name))
        seen.add(name)

        tmux_session = _as_str(a.get("tmux_session"))
        if not tmux_session:
            issues.append(ValidationIssue(level="error", message="missing tmux_session", agent=name))

        desired_state = _as_str(a.get("desired_state") or "running").lower()
        if desired_state not in {"running", "stopped"}:
            issues.append(ValidationIssue(level="error", message="desired_state must be running|stopped", agent=name))

        required = bool(a.get("required", False))
        status = _as_str(a.get("status") or "active").lower()

        # V2 agents use agent_type + cli_args instead of start_cmd
        agent_type = _as_str(a.get("agent_type"))
        start_cmd = _as_str(a.get("start_cmd"))
        should_run = desired_state == "running" or required
        if should_run and status != "inactive" and not start_cmd and not agent_type and not _has_runtime_manifest(a):
            issues.append(ValidationIssue(level="error", message="missing start_cmd or agent_type for running/required agent", agent=name))

        telegram_enabled = a.get("telegram_enabled", None)
        if telegram_enabled is not None and not isinstance(telegram_enabled, bool):
            issues.append(ValidationIssue(level="error", message="telegram_enabled must be boolean", agent=name))

        agent_name = _as_str(a.get("agent_name"))
        if agent_name and " " in agent_name:
            issues.append(ValidationIssue(level="error", message="agent_name must not contain spaces", agent=name))

    return issues
