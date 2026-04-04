from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.loader import YAMLConfigLoader
from config.registry_editor import (
    AgentEntry,
    append_agent_to_group,
    append_agent_to_registry_file,
    add_group_meta,
    get_registry_path,
)
from config.validator import validate_agents_registry, _collect_agents_from_groups


# ============================================================
# Group provisioning defaults
# ============================================================

DEFAULT_GROUP_ROLES = ["pmo", "architect", "devops"]

ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pmo": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Sonnet",
        "provider_model": "claude/Sonnet",
        "capabilities": [
            "project_management",
            "task_coordination",
            "progress_tracking",
            "resource_allocation",
            "risk_assessment",
        ],
        "tags": ["#pmo", "#coordinator", "#manager"],
    },
    "architect": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Opus",
        "provider_model": "claude/Opus",
        "capabilities": [
            "architecture_design",
            "code_review",
            "tech_decision",
            "documentation",
        ],
        "tags": ["#architect", "#design", "#review"],
    },
    "devops": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Sonnet",
        "provider_model": "claude/Sonnet",
        "capabilities": [
            "deployment",
            "infrastructure",
            "monitoring",
            "troubleshooting",
        ],
        "tags": ["#devops", "#ops", "#infra"],
    },
    "developer": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Opus",
        "provider_model": "claude/Opus",
        "capabilities": [
            "code_implementation",
            "debugging",
            "testing",
            "optimization",
        ],
        "tags": ["#developer", "#coder", "#impl"],
    },
    "qa": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Sonnet",
        "provider_model": "claude/Sonnet",
        "capabilities": [
            "quality_assurance",
            "testing",
            "code_review",
            "documentation",
        ],
        "tags": ["#qa", "#testing", "#quality"],
    },
    "researcher": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Sonnet",
        "provider_model": "claude/Sonnet",
        "capabilities": [
            "data_analysis",
            "reporting",
            "searching",
        ],
        "tags": ["#researcher", "#analyst"],
    },
    "frontdesk": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Haiku",
        "provider_model": "claude/Haiku",
        "capabilities": [
            "message_routing",
            "telegram_gateway",
            "fallback_handler",
            "agent_dispatch",
        ],
        "tags": ["#operator", "#router", "#gateway"],
    },
    "ui-designer": {
        "agent_type": "claude",
        "agent_cli": "",
        "agent_model": "Sonnet",
        "provider_model": "claude/Sonnet",
        "capabilities": [
            "ui_design",
            "ux_design",
            "frontend_development",
            "prototype_creation",
        ],
        "tags": ["#designer", "#ui", "#ux", "#frontend"],
    },
}

# Fallback for unknown/custom roles
ROLE_FALLBACK: dict[str, Any] = {
    "agent_type": "claude",
    "agent_cli": "",
    "agent_model": "Sonnet",
    "provider_model": "claude/Sonnet",
    "capabilities": [],
    "tags": [],
}



_TYPE_PROFILE_DIRS = [
    Path("/xkagent_infra/brain/base/spec/templates/type_profiles"),
    Path("/xkagent_infra/brain/base/spec/templates/agent/type_profiles"),
]


def _iter_type_profile_files():
    seen: set[str] = set()
    for base_dir in _TYPE_PROFILE_DIRS:
        if not base_dir.exists():
            continue
        for yaml_file in sorted(base_dir.glob("*.yaml")):
            key = yaml_file.name
            if key in seen:
                continue
            seen.add(key)
            yield yaml_file


def load_type_profile(profile_id: str) -> "dict | None":
    """按 variant id 查找 type profile，返回三字段配置或 None。"""
    import yaml as _yaml

    if not any(d.exists() for d in _TYPE_PROFILE_DIRS):
        return None
    for yaml_file in _iter_type_profile_files():
        try:
            data = _yaml.safe_load(yaml_file.read_text())
        except Exception:
            continue
        for _role_key, role_data in (data.get("profiles") or {}).items():
            for variant in (role_data.get("variants") or []):
                if variant.get("id") == profile_id:
                    cli = variant.get("agent_cli", variant.get("cli_type", ""))
                    model = variant.get("agent_model", variant.get("model", "Sonnet"))
                    return {
                        "agent_type": variant.get("agent_type", "claude"),
                        "agent_cli": cli,
                        "agent_model": model,
                        # legacy aliases
                        "cli_type": cli,
                        "model": model,
                        "effort": variant.get("effort", ""),
                        "reason": variant.get("reason", ""),
                    }
    return None


def list_type_profiles(role_filter: str = "") -> "list[dict]":
    """列出所有可用 type profiles，可按 role 过滤。"""
    import yaml as _yaml

    results = []
    if not any(d.exists() for d in _TYPE_PROFILE_DIRS):
        return results
    for yaml_file in _iter_type_profile_files():
        try:
            data = _yaml.safe_load(yaml_file.read_text())
        except Exception:
            continue
        category = data.get("category", "")
        for role_key, role_data in (data.get("profiles") or {}).items():
            if role_filter and role_key != role_filter:
                continue
            for variant in (role_data.get("variants") or []):
                results.append({
                    "id": variant.get("id", ""),
                    "role": role_key,
                    "category": category,
                    "agent_type": variant.get("agent_type", "claude"),
                    "agent_cli": variant.get("agent_cli", variant.get("cli_type", "")),
                    "agent_model": variant.get("agent_model", variant.get("model", "")),
                    "model": variant.get("agent_model", variant.get("model", "")),
                    "reason": variant.get("reason", ""),
                    "is_default": variant.get("id") == role_data.get("default"),
                })
    return results

# ============================================================
# Legacy single-agent provisioning (V1)
# ============================================================

@dataclass(frozen=True)
class ProvisionSpec:
    name: str  # logical name used by manager routing / orchestrator control
    base_agent: str  # claude | codex | service
    cwd: str = "/xkagent_infra/brain"
    tmux_session: str | None = None
    start_cmd: str | None = None
    required: bool = False
    desired_state: str = "running"
    status: str = "active"
    description: str = ""
    tags: list[str] | None = None
    capabilities: list[str] | None = None


def _clean(s: Any) -> str:
    return str(s or "").strip()


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}


def _workspace_dir(name: str) -> Path:
    return Path("/xkagent_infra/runtime/agents") / name


class Provisioner:
    """Provision agents and groups managed by service-agentctl.

    Supports:
      - V1: provision_agent() — single agent via ProvisionSpec
      - V2: provision_group() — batch create agents for a group
    """

    def __init__(self, *, audit_logger: Any = None, config_loader: YAMLConfigLoader, launcher: Any) -> None:
        self._audit = audit_logger
        self._config = config_loader
        self._launcher = launcher

    # ============================================================
    # V2: Group provisioning
    # ============================================================

    def provision_group(
        self,
        group_id: str,
        *,
        display_name: str = "",
        group_type: str = "coding",
        description: str = "",
        roles: list[str] | None = None,
        desired_state: str = "stopped",
    ) -> list[str]:
        """Provision a new group with its standard agents.

        Args:
            group_id: Group identifier (e.g. "digital_resources").
            display_name: Human-readable name (defaults to group_id).
            group_type: "coding" or "service".
            description: Group description for group_meta.
            roles: List of roles to create (defaults to DEFAULT_GROUP_ROLES).
            desired_state: Initial desired_state for all agents ("stopped" or "running").

        Returns:
            List of created agent names.
        """
        if self._audit:
            self._audit.log_event("provision_group_requested", {"group_id": group_id, "roles": roles})

        # Validate group_id format
        if not group_id or not group_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"invalid group_id: {group_id!r} (must be alphanumeric with _ or -)")

        # Check group doesn't already exist
        cfg = self._config.get_agents_registry()
        root = cfg if isinstance(cfg, dict) else {}
        groups = root.get("groups", {})
        if isinstance(groups, dict) and group_id in groups:
            raise ValueError(f"group already exists: {group_id}")

        if roles is None:
            roles = list(DEFAULT_GROUP_ROLES)

        registry_path = get_registry_path(self._config.config_dir)
        created_agents: list[str] = []
        group_base = Path(f"/xkagent_infra/groups/org/{group_id}")

        # 1. Add group_meta entry
        desc = description or f"{display_name or group_id} group"
        add_group_meta(registry_path, group_id, group_type, desc)

        # 2. Create each agent
        for role in roles:
            agent_name = f"agent_{group_id}_{role}"
            agent_dir = group_base / "agents" / agent_name
            role_defaults = ROLE_DEFAULTS.get(role, ROLE_FALLBACK)

            entry = AgentEntry(
                name=agent_name,
                tmux_session=agent_name,
                cwd=str(agent_dir),
                description=f"{display_name or group_id} 的 {role} Agent",
                role=role,
                scope="group",
                group=group_id,
                path=str(agent_dir),
                agent_type=role_defaults.get("agent_type", "claude"),
                agent_cli=role_defaults.get("agent_cli", ""),
                agent_model=role_defaults.get("agent_model", "Sonnet"),
                cli_args=["--dangerously-skip-permissions"],
                env={"IS_SANDBOX": "1"},
                export_cmd={"BRAIN_AGENT_NAME": agent_name},
                required=False,
                desired_state=desired_state,
                status="active",
                capabilities=role_defaults.get("capabilities"),
                tags=role_defaults.get("tags"),
            )

            # Create agent directory
            agent_dir.mkdir(parents=True, exist_ok=True)

            # Append to registry under groups
            # Force reload to pick up previous writes
            self._config.force_reload("agents_registry.yaml")
            append_agent_to_group(registry_path, group_id, entry)

            created_agents.append(agent_name)

        # 3. Generate configs (CLAUDE.md + .mcp.json) for all new agents
        self._config.force_reload("agents_registry.yaml")
        try:
            from services.config_generator import generate_all_configs
            for agent_name in created_agents:
                agent_dir = group_base / "agents" / agent_name
                role = agent_name.rsplit("_", 1)[-1]
                role_defaults = ROLE_DEFAULTS.get(role, ROLE_FALLBACK)
                spec = {
                    "name": agent_name,
                    "agent_type": role_defaults.get("agent_type", "claude"),
                    "agent_cli": role_defaults.get("agent_cli", ""),
                    "agent_model": role_defaults.get("agent_model", "Sonnet"),
                    "provider_model": role_defaults.get("provider_model", "claude/Sonnet"),
                    "cwd": str(agent_dir),
                    "role": role,
                    "group": group_id,
                    "path": str(agent_dir),
                    "capabilities": role_defaults.get("capabilities", []),
                }
                generate_all_configs(spec, force_claude_md=True)
        except ImportError:
            pass  # config_generator not available in all contexts

        # 4. Generate agent_roster.yaml
        self._generate_roster(group_id, group_base, created_agents, roles)

        if self._audit:
            self._audit.log_event("provision_group_completed", {
                "group_id": group_id,
                "agents": created_agents,
            })

        return created_agents

    def _generate_roster(self, group_id: str, group_base: Path, agents: list[str], roles: list[str]) -> None:
        """Generate workflow/pmo/agent_roster.yaml for the group."""
        roster_dir = group_base / "workflow" / "pmo"
        roster_dir.mkdir(parents=True, exist_ok=True)
        roster_path = roster_dir / "agent_roster.yaml"

        lines = [
            f"# {group_id} PMO Agent Roster",
            f"# Managed by agentctl provision-group",
            "",
            "roster:",
            f"  group_id: {group_id}",
            f"  owner: agent_{group_id}_pmo",
            "",
            "agents:",
        ]

        for agent_name in agents:
            role = agent_name.rsplit("_", 1)[-1]
            lines.extend([
                f"  - agent_name: {agent_name}",
                f"    type: resident",
                f"    role: {role}",
                f"    status: active",
                f"    current_tasks: []",
                f"    recent_completions: []",
                "",
            ])

        roster_path.write_text("\n".join(lines), encoding="utf-8")

    # ============================================================
    # V1: Single agent provisioning (legacy)
    # ============================================================

    def provision_agent(self, spec: dict[str, Any]) -> None:
        if self._audit:
            self._audit.log_event("provision_agent_requested", {"spec": spec})

        ps = self._normalize(spec)
        self._validate_preflight(ps)

        ws = _workspace_dir(ps.name)
        ws.mkdir(parents=True, exist_ok=True)
        self._write_runtime_files(ws, ps)

        entry = self._registry_entry(ps)
        registry_path = get_registry_path(self._config.config_dir)
        append_agent_to_registry_file(registry_path, entry)

        self._launcher.reload_config()
        if ps.desired_state.lower() == "running" or ps.required:
            self._launcher.restart(ps.name, reason="provisioned")

        if self._audit:
            self._audit.log_event(
                "provision_agent_completed",
                {"name": ps.name, "tmux_session": entry.tmux_session, "base_agent": ps.base_agent},
            )

    def _normalize(self, spec: dict[str, Any]) -> ProvisionSpec:
        name = _clean(spec.get("name"))
        base_agent = _clean(spec.get("base_agent") or spec.get("agent") or "")
        cwd = _clean(spec.get("cwd") or "/xkagent_infra/brain") or "/xkagent_infra/brain"
        tmux_session = _clean(spec.get("tmux_session") or "") or None
        start_cmd = _clean(spec.get("start_cmd") or "") or None
        required = _as_bool(spec.get("required", False))
        desired_state = _clean(spec.get("desired_state") or "running") or "running"
        status = _clean(spec.get("status") or "active") or "active"
        description = _clean(spec.get("description") or "")
        tags = spec.get("tags")
        capabilities = spec.get("capabilities")
        if not isinstance(tags, list):
            tags = None
        if not isinstance(capabilities, list):
            capabilities = None
        return ProvisionSpec(
            name=name,
            base_agent=base_agent,
            cwd=cwd,
            tmux_session=tmux_session,
            start_cmd=start_cmd,
            required=required,
            desired_state=desired_state,
            status=status,
            description=description,
            tags=[_clean(x) for x in tags] if tags else None,
            capabilities=[_clean(x) for x in capabilities] if capabilities else None,
        )

    def _validate_preflight(self, ps: ProvisionSpec) -> None:
        if not ps.name:
            raise ValueError("provision spec missing name")
        if any(ch.isspace() for ch in ps.name):
            raise ValueError("name must not contain spaces")
        if "/" in ps.name or "\\" in ps.name:
            raise ValueError("name must not contain path separators")

        if ps.base_agent not in {"claude", "codex", "service"}:
            raise ValueError("base_agent must be one of: claude|codex|service")

        if ps.desired_state.strip().lower() not in {"running", "stopped"}:
            raise ValueError("desired_state must be running|stopped")

        cfg = self._config.get_agents_registry()
        issues = validate_agents_registry(cfg)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            msg = "; ".join([f"{e.agent+': ' if e.agent else ''}{e.message}" for e in errors])[:400]
            raise ValueError(f"agents_registry.yaml invalid (fix first): {msg}")

        # Check for duplicate name in both V1 agents: and V2 groups: structures
        root = cfg.get("agents_registry", {}) if isinstance(cfg, dict) else {}
        if not isinstance(root, dict):
            root = cfg if isinstance(cfg, dict) else {}

        # V2: check groups
        all_agents = _collect_agents_from_groups(root)
        for a in all_agents:
            if isinstance(a, dict) and _clean(a.get("name")) == ps.name:
                raise ValueError(f"agent already exists: {ps.name}")

        # V1 fallback: check agents list
        agents = root.get("agents", []) if isinstance(root, dict) else []
        if isinstance(agents, list):
            for a in agents:
                if isinstance(a, dict) and _clean(a.get("name")) == ps.name:
                    raise ValueError(f"agent already exists: {ps.name}")

    def _tmux_session_for(self, ps: ProvisionSpec) -> str:
        if ps.tmux_session:
            return ps.tmux_session
        if ps.base_agent in {"claude", "codex"}:
            return f"{ps.base_agent}_{ps.name}"
        return ps.name

    def _start_cmd_for(self, ps: ProvisionSpec) -> str:
        if ps.start_cmd:
            return ps.start_cmd
        if ps.base_agent == "claude":
            return "bash -lc 'claude --resume'"
        if ps.base_agent == "codex":
            return "bash -lc 'codex --resume'"
        raise ValueError("service base_agent requires explicit start_cmd")

    def _registry_entry(self, ps: ProvisionSpec) -> AgentEntry:
        tmux_session = self._tmux_session_for(ps)
        start_cmd = self._start_cmd_for(ps)
        agent_name = ps.base_agent if ps.base_agent in {"claude", "codex"} else ps.name
        return AgentEntry(
            name=ps.name,
            description=ps.description or f"Provisioned agent ({ps.base_agent})",
            agent_name=agent_name if ps.base_agent in {"claude", "codex"} else "",
            tmux_session=tmux_session,
            cwd=ps.cwd,
            start_cmd=start_cmd,
            required=ps.required,
            desired_state=ps.desired_state,
            status=ps.status,
            tags=ps.tags,
            capabilities=ps.capabilities,
        )

    def _write_runtime_files(self, ws: Path, ps: ProvisionSpec) -> None:
        agents_md = ws / "AGENTS.md"
        init_md = ws / "INIT.md"

        tmux_session = self._tmux_session_for(ps)
        start_cmd = self._start_cmd_for(ps)

        if not agents_md.exists():
            agents_md.write_text(
                "\n".join(
                    [
                        f"# {ps.name}",
                        "",
                        "Scoped runtime directory for one provisioned agent instance.",
                        "",
                        "## Lifecycle",
                        f"- base_agent: `{ps.base_agent}`",
                        f"- tmux session: `{tmux_session}`",
                        f"- cwd: `{ps.cwd}`",
                        f"- start_cmd: `{start_cmd}`",
                        "",
                        "## Control",
                        "- Managed by `service-agentctl` via `/xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml`.",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        if not init_md.exists():
            init_md.write_text(
                "\n".join(
                    [
                        f"# INIT — {ps.name}",
                        "",
                        "This file defines agent-local operational notes (human-facing).",
                        "",
                        "## Defaults",
                        "- Use Brain IPC for coordination; avoid hardcoding pane ids in targets.",
                        "- Treat `agents_registry.yaml` as SSOT for lifecycle config.",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
