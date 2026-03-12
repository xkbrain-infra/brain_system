"""Shared config generator for agent MCP, CLAUDE.md, and Codex configs.

Extracted from launcher.py to be reusable by both the CLI (agentctl) and the
service daemon (Launcher).
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

# Default MCP server - every agent must bind IPC (C version)
DEFAULT_MCP_SERVER = {
    "mcp-brain_ipc_c": {
        "command": "/brain/bin/mcp/mcp-brain_ipc_c",
        "args": [],
    },
    "mcp-brain_google_api": {
        "command": "/brain/bin/mcp/mcp-brain_google_api",
        "args": [],
        "env": {
            "GOOGLE_CREDENTIALS_PATH": "/brain/secrets/brain_google_api/credentials.json",
        },
    },
}

TEMPLATE_DIR = Path("/brain/base/spec/templates/agent")
CORE_TEMPLATE_DIR = Path("/brain/base/spec/templates/core")
ROLE_TEMPLATE_DIR = Path("/brain/base/spec/templates/roles")
LEGACY_TEMPLATE_DIR = Path("/brain/base/spec/templates/agent")
RUNTIME_MANIFEST_RELATIVE_PATH = ".brain/agent_runtime.json"


# ------------------------------------------------------------------
# MCP config generation
# ------------------------------------------------------------------

def generate_mcp_config(
    agent_name: str,
    agent_type: str,
    cwd: str,
    spec: dict[str, Any],
) -> None:
    """Generate MCP config (.mcp.json, .codex/config.toml, or .kimi/config.toml) for an agent.

    Args:
        agent_name: Agent name used as BRAIN_AGENT_NAME.
        agent_type: "claude", "codex", or "kimi".
        cwd: Agent working directory.
        spec: Full agent spec dict from registry (for extra mcp_servers, model, etc.)
    """
    if not agent_type or not agent_name or not cwd:
        return

    mcp_servers = copy.deepcopy(DEFAULT_MCP_SERVER)
    mcp_servers["mcp-brain_ipc_c"]["env"] = {
        "BRAIN_AGENT_NAME": agent_name,
        "BRAIN_TMUX_SESSION": agent_name,  # session name == agent name
        "BRAIN_DAEMON_AUTOSTART": "0",
    }

    extra = spec.get("mcp_servers") or {}
    if isinstance(extra, dict):
        mcp_servers.update(extra)

    # Check cli_type first - it overrides agent_type for config generation
    cli_type = str(spec.get("cli_type") or "").strip().lower()

    if cli_type in ("claude", "claude_code"):
        # Use Claude Code CLI → generate .mcp.json
        _write_claude_mcp(cwd, mcp_servers)
    elif cli_type == "native":
        # Use native CLI → generate native config based on agent_type
        if agent_type == "codex":
            _write_codex_mcp(cwd, mcp_servers, spec)
        elif agent_type == "kimi":
            _write_kimi_mcp(cwd, mcp_servers, spec)
        elif agent_type == "gemini":
            _write_gemini_mcp(cwd, mcp_servers, spec)
        else:
            # Unknown native CLI - don't generate anything (native CLIs have their own config)
            pass
    else:
        # No cli_type specified - backward compatible, use agent_type
        if agent_type == "claude":
            _write_claude_mcp(cwd, mcp_servers)
        elif agent_type == "codex":
            _write_codex_mcp(cwd, mcp_servers, spec)
        elif agent_type == "kimi":
            _write_kimi_mcp(cwd, mcp_servers, spec)
        elif agent_type == "gemini":
            _write_gemini_mcp(cwd, mcp_servers, spec)
        else:
            # Unknown agent_type - fallback to Claude
            _write_claude_mcp(cwd, mcp_servers)


def runtime_manifest_path(cwd: str) -> Path:
    return Path(cwd) / RUNTIME_MANIFEST_RELATIVE_PATH


def load_runtime_manifest(cwd: str) -> dict[str, Any] | None:
    path = runtime_manifest_path(cwd)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_runtime_command(spec: dict[str, Any]) -> tuple[str, bool]:
    agent_type = str(spec.get("agent_type") or "").strip()
    cli_type = str(spec.get("cli_type") or spec.get("agent_cli") or "").strip().lower()
    if cli_type in ("claude", "claude_code"):
        return "claude", True
    if cli_type == "native":
        return agent_type, False
    if agent_type == "codex":
        return "codex", False
    if agent_type in ("claude", "kimi", "minimax", "chatgpt", "gemini", "openai", "copilot", "alibaba", "bytedance"):
        return "claude", True
    return agent_type, False


def generate_runtime_manifest(spec: dict[str, Any]) -> str | None:
    """Persist launch-time runtime details into the agent directory."""
    cwd = str(spec.get("cwd") or spec.get("path") or "").strip()
    agent_name = str(spec.get("name") or "").strip()
    agent_type = str(spec.get("agent_type") or "").strip()
    if not cwd or not agent_name or not agent_type:
        return None

    command, use_claude_cli = _resolve_runtime_command(spec)
    if not command:
        return None

    cli_args = [str(arg).strip() for arg in (spec.get("cli_args") or []) if str(arg).strip()]
    model = str(spec.get("model") or spec.get("agent_model") or "").strip()
    initial_prompt = str(spec.get("initial_prompt") or "").strip()
    env_map: dict[str, str] = {}

    raw_env = spec.get("env") or {}
    if isinstance(raw_env, dict):
        for key, value in raw_env.items():
            key = str(key).strip()
            value = str(value).strip()
            if key:
                env_map[key] = value

    raw_export = spec.get("export_cmd") or {}
    if isinstance(raw_export, dict):
        for key, value in raw_export.items():
            key = str(key).strip()
            value = str(value).strip()
            if key:
                env_map[key] = value

    if agent_type == "codex":
        env_map.setdefault("CODEX_HOME", f"{cwd}/.codex")
    elif agent_type == "kimi":
        env_map.setdefault("KIMI_HOME", f"{cwd}/.kimi")

    args: list[str] = []
    if model:
        if use_claude_cli:
            args.extend(["--model", model])
        elif agent_type in ("kimi", "gemini"):
            args.extend(["--model", model])

    if agent_type == "kimi" and not use_claude_cli:
        args.extend(["--mcp-config-file", f"{cwd}/.kimi/mcp.json"])
        kimi_subcommand = str(spec.get("kimi_subcommand") or "").strip()
        args.append(kimi_subcommand or "acp")

    args.extend(cli_args)
    if initial_prompt and use_claude_cli:
        args.append(initial_prompt)

    payload = {
        "version": 1,
        "agent_name": agent_name,
        "runtime": {
            "command": command,
            "args": args,
            "env": env_map,
            "agent_type": agent_type,
            "use_claude_cli": use_claude_cli,
        },
    }

    path = runtime_manifest_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _extract_model_from_runtime(runtime: dict[str, Any]) -> str:
    args = runtime.get("args") or []
    if not isinstance(args, list):
        return ""
    normalized = [str(arg).strip() for arg in args]
    for idx, arg in enumerate(normalized):
        if arg == "--model" and idx + 1 < len(normalized):
            return normalized[idx + 1]
    return ""


def _extract_launch_overrides_from_runtime(runtime: dict[str, Any]) -> tuple[list[str], str]:
    args = runtime.get("args") or []
    if not isinstance(args, list):
        return [], ""

    normalized = [str(arg).strip() for arg in args if str(arg).strip()]
    filtered: list[str] = []
    skip_next = False
    for arg in normalized:
        if skip_next:
            skip_next = False
            continue
        if arg == "--model":
            skip_next = True
            continue
        filtered.append(arg)

    use_claude_cli = bool(runtime.get("use_claude_cli"))
    initial_prompt = ""
    if use_claude_cli and filtered and not filtered[-1].startswith("-"):
        initial_prompt = filtered.pop()

    return filtered, initial_prompt


def _write_claude_mcp(cwd: str, mcp_servers: dict[str, Any]) -> None:
    """Write .mcp.json for Claude Code agents.

    Standard MCP format:
    {
      "mcpServers": {
        "server_name": {
          "command": "path/to/executable",
          "args": [...],
          "env": {...}
        }
      }
    }
    """
    mcp_path = Path(cwd) / ".mcp.json"
    mcp_payload = {"mcpServers": mcp_servers}
    mcp_path.write_text(json.dumps(mcp_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_codex_mcp(cwd: str, mcp_servers: dict[str, Any], spec: dict[str, Any]) -> None:
    """Write .mcp.json (root) and .codex/config.toml for Codex agent.

    - Root: .mcp.json (standard MCP format)
    - .codex/: config.toml with [mcp_servers.*] sections
    """
    # Write root .mcp.json first
    mcp_path = Path(cwd) / ".mcp.json"
    mcp_payload = {"mcpServers": mcp_servers}
    mcp_path.write_text(json.dumps(mcp_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Then write .codex/config.toml
    codex_home = Path(cwd) / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    config_path = codex_home / "config.toml"

    model = str(spec.get("model") or "gpt-5.2-codex").strip()
    profile = str(spec.get("codex_profile") or "yolo").strip()
    trust_level = str(spec.get("trust_level") or "trusted").strip()
    reasoning_effort = str(spec.get("reasoning_effort") or "medium").strip()

    lines = [
        f'model = "{model}"',
        f'model_reasoning_effort = "{reasoning_effort}"',
        f'profile = "{profile}"',
        'suppress_unstable_features_warning = true',
        '',
        f'[projects."{cwd}"]',
        f'trust_level = "{trust_level}"',
        '',
        f'[profiles.{profile}]',
        'approval_policy = "never"',
        'sandbox_mode = "danger-full-access"',
        f'model = "{model}"',
        f'model_reasoning_effort = "{reasoning_effort}"',
        '',
        '[features]',
        'unified_exec = true',
        'shell_snapshot = true',
        'steer = true',
        'multi_agent = true',
        'apps = false',
    ]

    for name, config in mcp_servers.items():
        lines.append("")
        lines.append(f"[mcp_servers.{name}]")
        for key, value in config.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, list):
                items = ", ".join(f'"{v}"' for v in value)
                lines.append(f"{key} = [{items}]")
            elif isinstance(value, dict):
                items = ", ".join(f'{k} = "{v}"' for k, v in value.items())
                lines.append(f"{key} = {{ {items} }}")
            else:
                lines.append(f"{key} = {value}")

    lines.append("")
    config_path.write_text("\n".join(lines))


def _write_kimi_mcp(cwd: str, mcp_servers: dict[str, Any], spec: dict[str, Any]) -> None:
    """Write Kimi configs:
    - .kimi/config.toml: model/runtime defaults
    - .kimi/mcp.json: MCP servers (used by `kimi mcp` and `/mcp`)
    """
    kimi_home = Path(cwd) / ".kimi"
    kimi_home.mkdir(parents=True, exist_ok=True)
    config_path = kimi_home / "config.toml"
    mcp_path = kimi_home / "mcp.json"

    model = str(spec.get("model") or "kimi-code/kimi-for-coding").strip()

    lines = [
        f'default_model = "{model}"',
        'default_thinking = true',
        'default_yolo = false',
        '',
        f'[models."{model}"]',
        'provider = "managed:kimi-code"',
        f'model = "{model.split("/")[-1] if "/" in model else model}"',
        'max_context_size = 262144',
        'capabilities = ["video_in", "image_in", "thinking"]',
        '',
        '[providers."managed:kimi-code"]',
        'type = "kimi"',
        'base_url = "https://api.kimi.com/coding/v1"',
        'api_key = ""',
        '',
        '[providers."managed:kimi-code".oauth]',
        'storage = "file"',
        'key = "oauth/kimi-code"',
        '',
        '[loop_control]',
        'max_steps_per_turn = 100',
        'max_retries_per_step = 3',
        'max_ralph_iterations = 0',
        'reserved_context_size = 50000',
        '',
        '[mcp.client]',
        'tool_call_timeout_ms = 60000',
    ]

    for name, config in mcp_servers.items():
        lines.append("")
        lines.append(f"[mcp.servers.{name}]")
        for key, value in config.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, list):
                items = ", ".join(f'"{v}"' for v in value)
                lines.append(f"{key} = [{items}]")
            elif isinstance(value, dict):
                items = ", ".join(f'{k} = "{v}"' for k, v in value.items())
                lines.append(f"{key} = {{ {items} }}")
            else:
                lines.append(f"{key} = {value}")

    lines.append("")
    config_path.write_text("\n".join(lines), encoding="utf-8")

    # Kimi CLI interactive MCP registry
    mcp_payload = {"mcpServers": mcp_servers}
    mcp_path.write_text(json.dumps(mcp_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_gemini_mcp(cwd: str, mcp_servers: dict[str, Any], spec: dict[str, Any]) -> None:
    """Write Gemini CLI settings.json with MCP configuration.

    Gemini CLI reads MCP servers from ~/.gemini/settings.json under mcpServers.
    Format:
    {
      "mcpServers": {
        "serverName": {
          "command": "path/to/executable",
          "args": ["arg1"],
          "env": { "KEY": "value" },
          "timeout": 30000,
          "trust": false
        }
      }
    }
    """
    gemini_home = Path(cwd) / ".gemini"
    gemini_home.mkdir(parents=True, exist_ok=True)
    settings_path = gemini_home / "settings.json"

    # Transform MCP servers to Gemini CLI format
    # Original format: { "name": { "command": "...", "args": [...], "env": {...} } }
    # Gemini format: { "mcpServers": { "name": { "command": "...", "args": [...], "env": {...}, "timeout": 30000, "trust": false } } }
    gemini_servers = {}
    for name, config in mcp_servers.items():
        gemini_config = {
            "command": config.get("command", ""),
        }
        if config.get("args"):
            gemini_config["args"] = config["args"]
        if config.get("env"):
            gemini_config["env"] = config["env"]
        # Gemini CLI specific defaults
        gemini_config["timeout"] = 30000  # 30 second timeout
        gemini_config["trust"] = False  # Require confirmation for tools
        gemini_servers[name] = gemini_config

    # Write complete settings.json with MCP servers
    settings = {
        "mcpServers": gemini_servers,
        "mcp": {
            "allowed": list(gemini_servers.keys())
        }
    }
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------
# CLAUDE.md / AGENTS.md generation
# ------------------------------------------------------------------

def _load_role_sections(role: str) -> dict[str, str]:
    """Load role template and extract sections by ## heading."""
    role_file = ROLE_TEMPLATE_DIR / f"{role}.md"
    if not role_file.exists():
        role_file = LEGACY_TEMPLATE_DIR / "roles" / f"{role}.md"
    if not role_file.exists():
        return {}

    text = role_file.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _render_template(template: str, variables: dict[str, str]) -> str:
    """Replace {{variable}} placeholders in template with values.

    Runs two passes to handle variables inside section content
    (e.g., {{scope_path}} inside init_extra_refs section).
    """
    result = template
    for _ in range(2):
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", value)
    return result


def _process_conditionals(text: str, role: str) -> str:
    """Process {{#if role == "xxx"}}...{{/if}} blocks."""
    pattern = r'\{\{#if role == "(\w+)"\}\}(.*?)\{\{/if\}\}'
    def replacer(m: re.Match) -> str:
        if m.group(1) == role:
            return m.group(2)
        return ""
    return re.sub(pattern, replacer, text, flags=re.DOTALL)


def generate_claude_md(
    agent_name: str,
    role: str,
    group: str,
    spec: dict[str, Any],
    *,
    force: bool = False,
) -> str | None:
    """Generate CLAUDE.md (claude) or AGENTS.md (codex) from templates.

    Args:
        agent_name: Agent name.
        role: Role name (pmo, devops, architect, etc.).
        group: Group name.
        spec: Full agent spec dict from registry.
        force: If False, skip generation when target file already exists.

    Returns:
        Path of generated file, or None if skipped.
    """
    base_template_path = CORE_TEMPLATE_DIR / "base_template.md"
    if not base_template_path.exists():
        base_template_path = LEGACY_TEMPLATE_DIR / "base_template.md"
    if not base_template_path.exists():
        return None

    agent_type = str(spec.get("agent_type") or "claude").strip()
    cli_type = str(spec.get("cli_type") or "").strip().lower()
    cwd = str(spec.get("cwd") or "").strip()
    if not cwd:
        return None

    # Determine output filename based on agent_type (mapped to CLI)
    # - Claude CLI agents (claude, minimax, chatgpt) → CLAUDE.md
    # - Codex CLI → AGENTS.md
    # - Kimi CLI → 暂不生成（独立配置）
    # - Gemini CLI → 暂不生成（独立配置）
    if agent_type == "codex":
        filename = "AGENTS.md"
    elif agent_type in ("kimi", "gemini"):
        # Native CLI agents with their own configuration - skip markdown generation
        return None
    else:
        # Claude CLI agents (claude, minimax, chatgpt) or unknown
        filename = "CLAUDE.md"
    output_path = Path(cwd) / filename

    # Skip if file exists and force is not set
    if output_path.exists() and not force:
        return None

    # Load base template
    template = base_template_path.read_text(encoding="utf-8")

    # Load role sections
    role_sections = _load_role_sections(role)

    # Build scope_path from group
    scope_path = str(_GROUPS_BASE_DIR / group) if group else str(_GROUPS_BASE_DIR)

    # Build capabilities list
    capabilities = spec.get("capabilities") or []
    capabilities_list = "\n".join(f"- {c}" for c in capabilities) if capabilities else ""

    # Build variable map
    variables: dict[str, str] = {
        "name": spec.get("name") or agent_name,
        "agent_name": agent_name,
        "description": str(spec.get("description") or ""),
        "path": str(spec.get("path") or cwd),
        "scope_path": scope_path,
        "group": group,
        "role": role,
        "capabilities_list": capabilities_list,
        # Section placeholders from role template
        "role_identity": role_sections.get("role_identity", ""),
        "init_extra_refs": role_sections.get("init_extra_refs", ""),
        "core_responsibilities": role_sections.get("core_responsibilities", ""),
        "collaboration_extra": role_sections.get("collaboration_extra", ""),
        "health_check_extra": role_sections.get("health_check_extra", ""),
    }

    # Render template
    rendered = _render_template(template, variables)

    # Process conditionals
    rendered = _process_conditionals(rendered, role)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return str(output_path)


# ------------------------------------------------------------------
# Combined entry point
# ------------------------------------------------------------------

def generate_all_configs(
    spec: dict[str, Any],
    *,
    force_claude_md: bool = False,
) -> dict[str, Any]:
    """Generate all config files for an agent.

    Args:
        spec: Full agent spec dict from registry (must include name, agent_type, cwd, etc.)
        force_claude_md: If True, overwrite existing CLAUDE.md/AGENTS.md.

    Returns:
        Dict summarizing what was generated.
    """
    agent_name = str(spec.get("name") or "").strip()
    cwd = str(spec.get("cwd") or spec.get("path") or "").strip()
    role = str(spec.get("role") or "").strip()
    group = str(spec.get("group") or spec.get("_group") or "").strip()

    result: dict[str, Any] = {
        "agent_name": agent_name,
        "mcp_config": False,
        "claude_md": None,
    }

    if not agent_name or not cwd:
        result["error"] = "missing agent_name or cwd"
        return result

    existing_runtime_manifest = load_runtime_manifest(cwd)
    runtime = existing_runtime_manifest.get("runtime") if isinstance(existing_runtime_manifest, dict) else None
    agent_type = str(spec.get("agent_type") or "").strip()
    if not agent_type and isinstance(runtime, dict):
        agent_type = str(runtime.get("agent_type") or "").strip()
    cli_type = str(spec.get("cli_type") or spec.get("agent_cli") or "").strip().lower()
    if not cli_type and isinstance(runtime, dict):
        cli_type = "claude" if bool(runtime.get("use_claude_cli")) else "native"

    effective_spec = dict(spec)
    effective_spec.setdefault("cwd", cwd)
    if agent_type:
        effective_spec["agent_type"] = agent_type
    if cli_type:
        effective_spec["cli_type"] = cli_type
    if isinstance(runtime, dict):
        model = str(effective_spec.get("model") or "").strip()
        if not model:
            runtime_model = _extract_model_from_runtime(runtime)
            if runtime_model:
                effective_spec["model"] = runtime_model
        cli_args = effective_spec.get("cli_args")
        initial_prompt = str(effective_spec.get("initial_prompt") or "").strip()
        if not cli_args or not isinstance(cli_args, list) or not initial_prompt:
            runtime_cli_args, runtime_initial_prompt = _extract_launch_overrides_from_runtime(runtime)
            if (not cli_args or not isinstance(cli_args, list)) and runtime_cli_args:
                effective_spec["cli_args"] = runtime_cli_args
            if not initial_prompt and runtime_initial_prompt:
                effective_spec["initial_prompt"] = runtime_initial_prompt
        if "env" not in effective_spec and isinstance(runtime.get("env"), dict):
            effective_spec["env"] = dict(runtime.get("env") or {})
    if existing_runtime_manifest:
        result["runtime_manifest"] = str(runtime_manifest_path(cwd))

    # 1. Generate MCP config (.mcp.json or .codex/config.toml)
    if agent_type:
        generate_mcp_config(agent_name, agent_type, cwd, effective_spec)
        result["mcp_config"] = True

    # 2. Generate CLAUDE.md / AGENTS.md (only if role is specified)
    if role and agent_type:
        md_path = generate_claude_md(
            agent_name, role, group, effective_spec, force=force_claude_md,
        )
        result["claude_md"] = md_path

    # 3. Generate .claude/settings.local.json (only for Claude Code CLI agents)
    # Only generate Claude settings for agents that use Claude CLI
    # - Explicitly set cli_type=claude
    # - Legacy implicit claude-cli agent types
    needs_claude_settings = (
        cli_type in ("claude", "claude_code")
        or (not cli_type and agent_type in (
            "claude", "minimax", "chatgpt", "kimi", "gemini", "alibaba", "bytedance", "openai", "copilot"
        ))
    )
    if needs_claude_settings and agent_type:
        settings_path = _generate_settings_local(cwd, role, group, effective_spec)
        if settings_path:
            result["settings_local"] = settings_path

    runtime_path = generate_runtime_manifest(effective_spec)
    if runtime_path:
        result["runtime_manifest"] = runtime_path

    return result


# ------------------------------------------------------------------
# Settings.local.json generation
# ------------------------------------------------------------------

_SECRETS_FILE = Path("/brain/secrets/system/agents/llm_tokens.env")
_GROUPS_BASE_DIR = Path("/xkagent_infra/groups")

# agent_type -> provider_id in brain_agent_proxy (proxy-first defaults)
_AGENT_TYPE_PROXY_PROVIDER_MAP: dict[str, str] = {
    "claude": "claude",
    "openai": "openai",
    "copilot": "copilot",
    "gemini": "gemini",
    "minimax": "minimax",
    "alibaba": "alibaba",
    "bytedance": "bytedance",
}

# agent_type → secrets env var mapping (API credentials)
_AGENT_TYPE_SECRETS_MAP: dict[str, dict[str, str]] = {
    "kimi": {
        "ANTHROPIC_API_KEY": "KIMI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN": "KIMI_API_KEY",
        "ANTHROPIC_BASE_URL": "KIMI_API_BASE",
    },
    "minimax": {
        "ANTHROPIC_API_KEY": "MINIMAX_API_KEY",
        "ANTHROPIC_AUTH_TOKEN": "MINIMAX_API_KEY",
        "ANTHROPIC_BASE_URL": "MINIMAX_API_BASE",
    },
    "chatgpt": {
        "ANTHROPIC_API_KEY": "LITELLM_MASTER_KEY",
        "ANTHROPIC_AUTH_TOKEN": "LITELLM_MASTER_KEY",
        "ANTHROPIC_BASE_URL": "LITELLM_ANTHROPIC_BASE",
    },
    "gemini": {
        "ANTHROPIC_API_KEY": "GEMINI_API_KEY",
        "ANTHROPIC_BASE_URL": "GEMINI_API_BASE",
    },
    "openai": {
        "ANTHROPIC_API_KEY": "OPENAI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN": "OPENAI_API_KEY",
        "ANTHROPIC_BASE_URL": "OPENAI_API_BASE",
    },
    "alibaba": {
        "ANTHROPIC_API_KEY": "QWEN_API_KEY",
        "ANTHROPIC_AUTH_TOKEN": "QWEN_API_KEY",
        "ANTHROPIC_BASE_URL": "QWEN_API_BASE",
    },
    "bytedance": {
        "ANTHROPIC_API_KEY": "BYTEDANCE_API_KEY",
        "ANTHROPIC_AUTH_TOKEN": "BYTEDANCE_API_KEY",
        "ANTHROPIC_BASE_URL": "BYTEDANCE_API_BASE",
    },
}

# agent_type → base_url override (when secrets file value is wrong/outdated)
_AGENT_TYPE_BASE_URL: dict[str, str] = {
    "kimi": "https://api.kimi.com/coding/",
    "minimax": "https://api.minimaxi.com/anthropic",
    "chatgpt": "http://localhost:8001/anthropic",
    "alibaba": "https://coding.dashscope.aliyuncs.com/apps/anthropic",
    "bytedance": "https://ark.cn-beijing.volces.com/api/coding",
}

# agent_type → hardcoded fallback env values (used when secrets are absent)
_AGENT_TYPE_FALLBACK_ENV: dict[str, dict[str, str]] = {
    "chatgpt": {
        "ANTHROPIC_API_KEY": "sk-brain-litellm-2026",
        "ANTHROPIC_AUTH_TOKEN": "sk-brain-litellm-2026",
    },
}

# Standard plugins enabled for all agents
_ENABLED_PLUGINS: dict[str, bool] = {
    "frontend-design@claude-plugins-official": True,
    "context7@claude-plugins-official": True,
    "ralph-loop@claude-plugins-official": True,
    "feature-dev@claude-plugins-official": True,
    "code-review@claude-plugins-official": True,
    "playwright@claude-plugins-official": True,
    "plugin-dev@claude-plugins-official": True,
    "firebase@claude-plugins-official": True,
    "code-simplifier@claude-plugins-official": True,
    "claude-md-management@claude-plugins-official": True,
    "greptile@claude-plugins-official": True,
}

# Status line command (shows model, dir, context usage)
_STATUS_LINE = {
    "type": "command",
    "command": (
        'input=$(cat); '
        'model=$(echo "$input" | jq -r \'.model.display_name // "Claude"\'); '
        'dir=$(echo "$input" | jq -r \'.workspace.current_dir // "~"\'); '
        'used=$(echo "$input" | jq -r \'.context_window.used_percentage // empty\'); '
        'if [ -n "$used" ]; then '
        'printf "%s | %s | Context: %.1f%% used" "$model" "$dir" "$used"; '
        'else printf "%s | %s" "$model" "$dir"; fi'
    ),
}


def _load_secrets() -> dict[str, str]:
    """Load key=value pairs from secrets env file."""
    if not _SECRETS_FILE.exists():
        return {}
    result: dict[str, str] = {}
    for line in _SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _resolve_model_name(spec: dict[str, Any]) -> str:
    """Resolve the effective model name for env vars.

    Registry model might be 'kimi-code/kimi-for-coding' — extract the short name.
    """
    model = str(spec.get("model") or "").strip()
    if "/" in model:
        return model.split("/")[-1]
    return model


def _build_proxy_auth_token(agent_type: str, spec: dict[str, Any]) -> str:
    """Build deterministic proxy token.

    New canonical format:
      bgw-apx-v1--p-{provider}--m-{model_key}--n-{name}

    Keep only [a-z0-9_] for model/name segments to avoid parser ambiguity.
    """
    provider = _AGENT_TYPE_PROXY_PROVIDER_MAP.get(agent_type, "").strip()
    if not provider:
        return ""
    model_name = _resolve_model_name(spec)
    model_part = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_") or "default"
    name = str(spec.get("name") or "").strip().lower()
    name_part = re.sub(r"[^a-z0-9]+", "_", name).strip("_")[:32] or "dev"
    return f"bgw-apx-v1--p-{provider}--m-{model_part}--n-{name_part}"


def _build_model_selector(agent_type: str, spec: dict[str, Any]) -> str:
    """Build canonical model selector.

    Format: provider/model
    Example: minimax/MiniMax-M2.5
    """
    model_name = _resolve_model_name(spec)
    provider = _AGENT_TYPE_PROXY_PROVIDER_MAP.get(agent_type, "").strip()
    if provider and model_name:
        return f"{provider}/{model_name}"
    return model_name


def _resolve_transport_mode(spec: dict[str, Any]) -> str:
    """Resolve transport mode for Claude settings: proxy|direct."""
    mode = str(spec.get("transport_mode") or "").strip().lower()
    if mode in ("proxy", "direct"):
        return mode
    env_cfg = spec.get("env") or {}
    if isinstance(env_cfg, dict):
        env_mode = str(env_cfg.get("BRAIN_TRANSPORT_MODE") or "").strip().lower()
        if env_mode in ("proxy", "direct"):
            return env_mode
    return "proxy"


def _build_settings_env(agent_type: str, spec: dict[str, Any]) -> dict[str, str]:
    """Build env dict for settings.local.json.

    For non-claude agent_types running via Claude Code CLI, injects:
    - API credentials from secrets
    - Model override env vars (ANTHROPIC_MODEL, DEFAULT_*_MODEL)
    - Timeout and traffic settings
    """
    transport_mode = _resolve_transport_mode(spec)
    if agent_type == "claude" and transport_mode == "direct":
        return {}

    env: dict[str, str] = {}
    # 1. Proxy-first defaults for provider-backed agent types.
    proxy_token = _build_proxy_auth_token(agent_type, spec)
    if proxy_token and transport_mode != "direct":
        env["ANTHROPIC_BASE_URL"] = os.environ.get("BRAIN_PROXY_BASE_URL", "http://127.0.0.1:8210")
        env["ANTHROPIC_AUTH_TOKEN"] = proxy_token
    else:
        # 1b. Legacy direct mode for non-proxy agent types.
        mapping = _AGENT_TYPE_SECRETS_MAP.get(agent_type)
        if mapping:
            secrets = _load_secrets()
            for target_var, source_var in mapping.items():
                val = secrets.get(source_var, "")
                if val:
                    env[target_var] = val
        fallback_env = _AGENT_TYPE_FALLBACK_ENV.get(agent_type) or {}
        for key, value in fallback_env.items():
            if key not in env and value:
                env[key] = value

        canonical_url = _AGENT_TYPE_BASE_URL.get(agent_type)
        if canonical_url:
            env["ANTHROPIC_BASE_URL"] = canonical_url

    # 2. Model env vars
    model_name = _build_model_selector(agent_type, spec)
    if model_name:
        env["ANTHROPIC_MODEL"] = model_name
        env["ANTHROPIC_SMALL_FAST_MODEL"] = model_name
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model_name
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model_name
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model_name

    # 3. Timeout and traffic settings
    env["API_TIMEOUT_MS"] = "3000000"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    return env


def _build_mcp_servers(agent_name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Build mcpServers config for settings.local.json."""
    mcp_servers: dict[str, Any] = {
        "mcp-brain_ipc_c": {
            "command": DEFAULT_MCP_SERVER["mcp-brain_ipc_c"]["command"],
            "args": [],
            "env": {
                "BRAIN_AGENT_NAME": agent_name,
                "BRAIN_DAEMON_AUTOSTART": "0",
            },
        },
    }
    # Merge extra mcp_servers from registry spec
    extra = spec.get("mcp_servers") or {}
    if isinstance(extra, dict):
        mcp_servers.update(extra)
    return mcp_servers


def _generate_settings_local(
    cwd: str, role: str, group: str, spec: dict[str, Any],
) -> str | None:
    """Generate .claude/settings.local.json for Claude Code CLI agents.

    Produces a complete settings file including:
    - permissions (bypassPermissions)
    - env (API credentials + model overrides for non-claude agents)
    - statusLine
    - enabledPlugins
    - language
    - mcpServers (mcp-brain_ipc_c + extras)
    - skipDangerousModePermissionPrompt
    - hooks (if configured in registry)
    """
    claude_dir = Path(cwd) / ".claude"
    settings_path = claude_dir / "settings.local.json"

    # Don't overwrite existing settings
    if settings_path.exists():
        return None

    claude_dir.mkdir(parents=True, exist_ok=True)

    agent_name = str(spec.get("name") or "").strip()
    agent_type = str(spec.get("agent_type") or "claude").strip()

    # --- Build settings ---
    settings: dict[str, Any] = {}

    # 1. Permissions — use dontAsk + allow list (works reliably with Kimi/non-claude models)
    settings["permissions"] = {
        "allow": [
            "Bash:*:*",
            "Read:*:*",
            "Edit:*:*",
            "Write:*:*",
            "Glob:*:*",
            "Grep:*:*",
            "Task:*:*",
            "Skill:*:*",
            "mcp__*:*",
            "AskUserQuestion:*:*",
            "NotebookEdit:*:*",
        ],
        "defaultMode": "bypassPermissions",
    }

    # 2. Env (non-claude agent types need API credential + model mapping)
    env_map = _build_settings_env(agent_type, spec)
    if env_map:
        settings["env"] = env_map

    # 3. Status line
    settings["statusLine"] = copy.deepcopy(_STATUS_LINE)

    # 4. Enabled plugins
    settings["enabledPlugins"] = copy.deepcopy(_ENABLED_PLUGINS)

    # 5. Language
    settings["language"] = "中文"

    # 6. MCP servers
    settings["mcpServers"] = _build_mcp_servers(agent_name, spec)

    # 7. Skip dangerous mode prompt
    settings["skipDangerousModePermissionPrompt"] = True

    # 8. Disable spinner tips (cleaner output for automated agents)
    settings["spinnerTipsEnabled"] = False

    # 9. Hooks (only if configured in registry)
    hooks_list = spec.get("hooks") or []
    if hooks_list:
        hooks_config: dict[str, Any] = {}
        hooks_base = "/brain/infrastructure/service/agent_abilities"

        # hooks_version pinning: lock agent to a specific release snapshot
        # If set, points to releases/{version}/bin/v2 instead of bin/current
        hooks_version = str(spec.get("hooks_version") or "").strip()
        if hooks_version:
            hook_bin_dir = f"{hooks_base}/releases/{hooks_version}/bin/v2"
        else:
            hook_bin_dir = f"{hooks_base}/bin/hooks/current"

        role_group = f"{role}-{group}" if role and group else role or "default"
        scope_path = str(_GROUPS_BASE_DIR / group) if group else str(_GROUPS_BASE_DIR)

        # Role context env vars - passed to every hook process
        hook_env = {
            "BRAIN_AGENT_NAME": agent_name,
            "BRAIN_AGENT_ROLE": role or "default",
            "BRAIN_AGENT_GROUP": group or "",
            "BRAIN_SCOPE_PATH": scope_path,
        }

        if "pre_tool_use" in hooks_list:
            hooks_config["PreToolUse"] = [{
                "matcher": "Bash|Edit|Glob|Grep|Read|Write",
                "hooks": [{
                    "type": "command",
                    "command": f"{hook_bin_dir}/pre_tool_use",
                    "timeout": 5000,
                    "description": f"LEP Engine - {role_group} PreToolUse",
                    "env": hook_env,
                }],
            }]

        if "post_tool_use" in hooks_list:
            hooks_config["PostToolUse"] = [{
                "matcher": "Bash|Edit|Glob|Grep|Read|Write",
                "hooks": [{
                    "type": "command",
                    "command": f"{hook_bin_dir}/post_tool_use",
                    "timeout": 5000,
                    "description": f"LEP Engine - {role_group} PostToolUse audit",
                    "env": hook_env,
                }],
            }]

        if "session_start" in hooks_list:
            hooks_config["SessionStart"] = [{
                "hooks": [{
                    "type": "command",
                    "command": f"{hook_bin_dir}/session_start",
                    "timeout": 5000,
                    "description": f"LEP Engine - {role_group} SessionStart",
                    "env": hook_env,
                }],
            }]

        if "session_end" in hooks_list:
            hooks_config["SessionEnd"] = [{
                "hooks": [{
                    "type": "command",
                    "command": f"{hook_bin_dir}/session_end",
                    "timeout": 5000,
                    "description": f"LEP Engine - {role_group} SessionEnd",
                    "env": hook_env,
                }],
            }]

        if "user_prompt_submit" in hooks_list:
            hooks_config["UserPromptSubmit"] = [{
                "hooks": [{
                    "type": "command",
                    "command": f"{hook_bin_dir}/user_prompt_submit",
                    "timeout": 5000,
                    "description": f"LEP Engine - {role_group} UserPromptSubmit",
                    "env": hook_env,
                }],
            }]

        if hooks_config:
            settings["hooks"] = hooks_config

    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return str(settings_path)
