from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


_CLAUDE_FRONTENDS = {
    "claude",
    "kimi",
    "minimax",
    "chatgpt",
    "gemini",
    "openai",
    "copilot",
    "alibaba",
    "bytedance",
}

_AGENT_TYPE_PROXY_PROVIDER_MAP: dict[str, str] = {
    "claude": "claude",
    "kimi": "kimi",
    "openai": "openai",
    "copilot": "copilot",
    "gemini": "gemini",
    "minimax": "minimax",
    "alibaba": "alibaba",
    "bytedance": "bytedance",
}


def _uses_claude_cli(spec: dict[str, Any]) -> bool:
    cli_type = str(spec.get("cli_type") or spec.get("agent_cli") or "").strip().lower()
    agent_type = str(spec.get("agent_type") or "").strip().lower()
    if cli_type in ("claude", "claude_code"):
        return True
    if cli_type == "native":
        return False
    return agent_type in _CLAUDE_FRONTENDS


def _resolve_transport_mode(spec: dict[str, Any]) -> str:
    mode = str(spec.get("transport_mode") or "").strip().lower()
    if mode in ("proxy", "direct"):
        return mode
    env_cfg = spec.get("env") or {}
    if isinstance(env_cfg, dict):
        env_mode = str(env_cfg.get("BRAIN_TRANSPORT_MODE") or "").strip().lower()
        if env_mode in ("proxy", "direct"):
            return env_mode
    return "proxy"


def _resolve_proxy_provider(spec: dict[str, Any]) -> str:
    model = str(spec.get("model") or "").strip()
    if "/" in model:
        provider, _, _ = model.partition("/")
        return provider.strip().lower()
    agent_type = str(spec.get("agent_type") or "").strip().lower()
    return _AGENT_TYPE_PROXY_PROVIDER_MAP.get(agent_type, "").strip().lower()


def spec_requires_claude_auth(spec: dict[str, Any]) -> bool:
    if not isinstance(spec, dict):
        return False

    agent_type = str(spec.get("agent_type") or "").strip().lower()
    transport_mode = _resolve_transport_mode(spec)

    if transport_mode == "direct":
        return agent_type == "claude"

    if not _uses_claude_cli(spec):
        return False

    return _resolve_proxy_provider(spec) == "claude"


def claude_auth_status(cli_path: str | None = None) -> tuple[bool, str]:
    resolved = (cli_path or "").strip() or shutil.which("claude") or "claude"
    try:
        proc = subprocess.run(
            [resolved, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except FileNotFoundError:
        return False, "Claude CLI is not installed or not in PATH."
    except Exception as exc:
        return False, f"Unable to determine Claude auth status: {exc}"

    raw = (proc.stdout or proc.stderr or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            if proc.returncode == 0:
                return True, ""
            return False, f"Unable to parse `claude auth status --json`: {raw}"

        if bool(data.get("loggedIn")):
            return True, ""

        auth_method = str(data.get("authMethod") or "none").strip() or "none"
        api_provider = str(data.get("apiProvider") or "firstParty").strip() or "firstParty"
        return (
            False,
            "Claude provider backend is unavailable: local Claude CLI is not authenticated "
            f"(authMethod={auth_method}, apiProvider={api_provider}). "
            "Run `claude auth login` on the host first.",
        )

    if proc.returncode == 0:
        return True, ""
    return False, f"`claude auth status --json` exited with code {proc.returncode}"
