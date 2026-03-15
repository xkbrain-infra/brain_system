#!/usr/bin/env python3
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import shlex
import subprocess
import time
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config.loader import DEFAULT_CONFIG_DIR, YAMLConfigLoader
from services.config_generator import (
    generate_all_configs as _generate_all_configs,
    load_runtime_manifest as _load_runtime_manifest,
)

# SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_DaemonClient = _mod.DaemonClient

_SECRETS_FILE = Path("/brain/secrets/system/agents/llm_tokens.env")


@dataclass
class RestartResult:
    success: bool
    agent_name: str
    reason: str
    attempt: int
    error: str | None = None


@dataclass
class AgentState:
    name: str
    tmux_session: str
    restart_attempts: list[float] = field(default_factory=list)
    last_restart: float | None = None
    cooldown_until: float | None = None


@dataclass
class CleanupResult:
    """Result of cleanup operation."""
    stopped: list[str]
    failed: list[str]
    skipped: list[str]
    skipped_attached: list[str]
    total_time_seconds: float


class Launcher:
    """tmux lifecycle manager: start/stop/restart/reconcile based on config."""

    def __init__(
        self,
        *,
        self_name: str,
        check_interval_s: int = 10,
        max_attempts: int = 10,
        window_seconds: int = 600,
        backoff_base_seconds: int = 2,
        backoff_max_seconds: int = 60,
        audit_logger: Any = None,
        cleanup_before_start: bool = True,
        cleanup_timeout_seconds: int = 5,
        cleanup_skip_attached: bool = True,
    ) -> None:
        self.self_name = self_name
        self.check_interval_s = check_interval_s
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.audit_logger = audit_logger
        self.cleanup_before_start = cleanup_before_start
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.cleanup_skip_attached = cleanup_skip_attached

        self._agent_states: dict[str, AgentState] = {}
        self._config_loader = YAMLConfigLoader(config_dir=DEFAULT_CONFIG_DIR)
        self._ipc = _DaemonClient()

    def get_agent_spec(self) -> dict[str, dict[str, Any]]:
        return self._get_agent_spec()

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.audit_logger:
            self.audit_logger.log_event(event_type, payload)
            return
        ts = datetime.now().isoformat(timespec="seconds")
        print(f"[{ts}] [{event_type}] {json.dumps(payload, ensure_ascii=False)}")

    def _daemon_request(self, action: str, data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._ipc._send_request(action, data)
        except Exception:
            return None

    def reload_config(self) -> None:
        self._config_loader.reload()

    def set_desired_state(self, agent_name: str, desired_state: str) -> bool:
        """Persist desired_state for an agent in agents_registry.yaml.

        Returns True if the value changed, False if already in target state.
        """
        normalized = str(desired_state or "").strip().lower()
        if normalized not in {"running", "stopped"}:
            raise ValueError("desired_state must be running|stopped")

        config_path = self._config_loader.config_dir / "agents_registry.yaml"
        if not config_path.exists():
            raise ValueError(f"agents_registry.yaml not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError("invalid agents_registry.yaml: root must be mapping")

        found = False
        changed = False

        for section_name in ("groups", "projects"):
            section = data.get(section_name)
            if not isinstance(section, dict):
                continue
            for _, agents in section.items():
                if not isinstance(agents, list):
                    continue
                for agent in agents:
                    if not isinstance(agent, dict):
                        continue
                    if str(agent.get("name") or "").strip() != agent_name:
                        continue
                    found = True
                    current = str(agent.get("desired_state") or "running").strip().lower()
                    if current != normalized:
                        agent["desired_state"] = normalized
                        changed = True

        if not found:
            raise ValueError(f"unknown agent: {agent_name}")

        if changed:
            tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            tmp_path.replace(config_path)
            self.reload_config()

        self._log_event(
            "agent_desired_state_updated",
            {"agent_name": agent_name, "desired_state": normalized, "changed": changed},
        )
        return changed

    def _get_agent_spec(self) -> dict[str, dict[str, Any]]:
        """Extract agent spec from groups and projects hierarchy."""
        cfg = self._config_loader.get_agents_registry()
        if not isinstance(cfg, dict):
            return {}

        out: dict[str, dict[str, Any]] = {}

        # Extract from groups: { group_name: [agent_spec...] }
        groups = cfg.get("groups", {})
        if isinstance(groups, dict):
            for group_name, agents in groups.items():
                if not isinstance(agents, list):
                    continue
                for a in agents:
                    if not isinstance(a, dict):
                        continue
                    name = str(a.get("name") or "").strip()
                    tmux_session = str(a.get("tmux_session") or "").strip()
                    if not name or not tmux_session:
                        continue
                    a["_group"] = group_name
                    a["_scope"] = "group"
                    out[name] = a

        # Extract from projects: { "group/project": [agent_spec...] }
        projects = cfg.get("projects", {})
        if isinstance(projects, dict):
            for project_path, agents in projects.items():
                if not isinstance(agents, list):
                    continue
                for a in agents:
                    if not isinstance(a, dict):
                        continue
                    name = str(a.get("name") or "").strip()
                    tmux_session = str(a.get("tmux_session") or "").strip()
                    if not name or not tmux_session:
                        continue
                    a["_project"] = project_path
                    a["_scope"] = "project"
                    out[name] = a

        return out

    def _get_online_agents(self) -> set[str]:
        """Return configured spec names considered online.

        Supports logical names that map to a tmux-discovered agent_name via spec.agent_name.
        """
        resp = self._daemon_request("agent_list", {"include_offline": False}) or {}
        if resp.get("status") != "ok":
            return set()

        instances = resp.get("instances", []) or []
        if not isinstance(instances, list):
            instances = []

        spec = self._get_agent_spec()
        online: set[str] = set()

        for spec_name, spec in spec.items():
            if not isinstance(spec, dict):
                continue
            runtime_name = str(spec.get("agent_name") or spec_name).strip()
            tmux_session = str(spec.get("tmux_session") or "").strip()
            if not runtime_name:
                continue

            # If tmux session is specified, match by (agent_name, tmux_session).
            if tmux_session:
                for inst in instances:
                    if not isinstance(inst, dict):
                        continue
                    if not inst.get("online"):
                        continue
                    if str(inst.get("agent_name") or "") == runtime_name and str(inst.get("tmux_session") or "") == tmux_session:
                        online.add(spec_name)
                        break
            else:
                # Heartbeat-only agents: match by agent_name or instance_id.
                for inst in instances:
                    if not isinstance(inst, dict):
                        continue
                    if not inst.get("online"):
                        continue
                    if str(inst.get("agent_name") or "") == runtime_name or str(inst.get("instance_id") or "") == runtime_name:
                        online.add(spec_name)
                        break

        return online

    def _get_tmux_sessions(self) -> set[str]:
        try:
            p = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if p.returncode != 0:
                return set()
            return {line.strip() for line in (p.stdout or "").splitlines() if line.strip()}
        except Exception:
            return set()

    def _get_attached_sessions(self) -> set[str]:
        """Return set of tmux sessions that are currently attached."""
        try:
            p = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}:#{session_attached}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if p.returncode != 0:
                return set()
            attached = set()
            for line in (p.stdout or "").splitlines():
                line = line.strip()
                if ":" in line:
                    name, flag = line.rsplit(":", 1)
                    if flag == "1":
                        attached.add(name)
            return attached
        except Exception:
            return set()

    def _is_managed_session(self, session_name: str) -> bool:
        """Determine if a tmux session is managed by orchestrator."""
        # Exclude self and service sessions
        if session_name == self.self_name:
            return False
        if session_name.startswith("service-"):
            return False

        # Check if session is in registry
        spec = self._get_agent_spec()
        registry_sessions = {str(s.get("tmux_session") or "") for s in spec.values()}
        if session_name in registry_sessions:
            return True

        # Check if session matches agent naming pattern
        if session_name.startswith(("agent_", "codex_")):
            return True

        return False

    def _graceful_stop_session(self, session: str) -> tuple[bool, str]:
        """Gracefully stop a tmux session with fallback to force kill."""
        try:
            # Send exit command
            subprocess.run(
                ["tmux", "send-keys", "-t", session, "exit", "Enter"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            # Wait for graceful exit
            for _ in range(self.cleanup_timeout_seconds):
                time.sleep(1)
                if session not in self._get_tmux_sessions():
                    return True, "graceful"
            # Force kill
            p = subprocess.run(
                ["tmux", "kill-session", "-t", session],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if p.returncode == 0 or session not in self._get_tmux_sessions():
                return True, "forced"
            return False, f"kill failed: {(p.stderr or p.stdout or '').strip()}"
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)

    def stop_all_managed_agents(self) -> CleanupResult:
        """Stop all managed agent sessions before restart.

        Returns CleanupResult with lists of stopped, failed, skipped sessions.
        """
        start_time = time.time()
        stopped: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        skipped_attached: list[str] = []

        sessions = self._get_tmux_sessions()
        attached = self._get_attached_sessions() if self.cleanup_skip_attached else set()

        for session in sorted(sessions):
            if not self._is_managed_session(session):
                skipped.append(session)
                self._log_event("cleanup_skipped", {"session": session, "reason": "not_managed"})
                continue

            if self.cleanup_skip_attached and session in attached:
                skipped_attached.append(session)
                self._log_event("cleanup_skipped", {"session": session, "reason": "attached"})
                continue

            success, method = self._graceful_stop_session(session)
            if success:
                stopped.append(session)
                self._log_event("cleanup_stopped", {"session": session, "method": method})
            else:
                failed.append(session)
                self._log_event("cleanup_failed", {"session": session, "error": method})

        elapsed = time.time() - start_time
        result = CleanupResult(
            stopped=stopped,
            failed=failed,
            skipped=skipped,
            skipped_attached=skipped_attached,
            total_time_seconds=round(elapsed, 2),
        )
        self._log_event("cleanup_complete", {
            "stopped": len(stopped),
            "failed": len(failed),
            "skipped": len(skipped),
            "skipped_attached": len(skipped_attached),
            "total_time_seconds": result.total_time_seconds,
        })
        return result

    def is_running(self, name: str) -> bool:
        """Check if an agent's tmux session is currently running."""
        spec = self._get_agent_spec().get(name)
        if not spec:
            return False
        tmux_session = str(spec.get("tmux_session") or "").strip()
        if not tmux_session:
            return False
        return tmux_session in self._get_tmux_sessions()

    def _calculate_backoff(self, attempts: int) -> float:
        backoff = self.backoff_base_seconds * (2 ** min(attempts, 6))
        return min(backoff, self.backoff_max_seconds)

    def _should_restart(self, agent_name: str) -> tuple[bool, str]:
        state = self._agent_states.get(agent_name)
        if not state:
            return True, "first_restart"

        now = time.time()
        if state.cooldown_until and now < state.cooldown_until:
            remaining = int(state.cooldown_until - now)
            return False, f"in_cooldown ({remaining}s remaining)"

        state.restart_attempts = [t for t in state.restart_attempts if now - t < self.window_seconds]
        if len(state.restart_attempts) >= self.max_attempts:
            return False, f"max_attempts_reached ({self.max_attempts} in {self.window_seconds}s)"

        return True, "allowed"

    def stop(self, agent_name: str, reason: str = "stop", *, persist_desired_state: bool = False) -> None:
        spec = self._get_agent_spec().get(agent_name)
        if not spec:
            raise ValueError(f"unknown agent: {agent_name}")
        if persist_desired_state:
            self.set_desired_state(agent_name, "stopped")
        tmux_session = str(spec.get("tmux_session") or "").strip()
        if not tmux_session:
            raise ValueError("missing tmux_session")
        subprocess.run(["tmux", "kill-session", "-t", tmux_session], capture_output=True, timeout=8, check=False)
        self._log_event(
            "agent_stop",
            {
                "agent_name": agent_name,
                "tmux_session": tmux_session,
                "reason": reason,
                "persist_desired_state": persist_desired_state,
            },
        )

    def _build_start_command(self, spec: dict[str, Any]) -> str:
        """Build start command from directory runtime manifest or legacy registry fields.

        cli_type resolution (aligned with bin/agentctl _load_spec):
          - cli_type: claude/claude_code → use 'claude' CLI
          - cli_type: native             → use agent_type as CLI command
          - cli_type: (empty)            → infer from agent_type:
              codex → 'codex';
              claude/kimi/minimax/chatgpt/gemini/openai/copilot/alibaba/bytedance → 'claude';
              else → agent_type
        """
        cwd = str(spec.get("cwd") or spec.get("path") or "").strip()
        manifest = _load_runtime_manifest(cwd) if cwd else None
        runtime = manifest.get("runtime") if isinstance(manifest, dict) else None
        if isinstance(runtime, dict):
            command = str(runtime.get("command") or "").strip()
            args = [str(arg).strip() for arg in (runtime.get("args") or []) if str(arg).strip()]
            if command:
                return " ".join([command, *args]).strip()

        agent_type = str(spec.get("agent_type") or "").strip()
        cli_type = str(spec.get("cli_type") or "").strip().lower()
        model = str(spec.get("model") or "").strip()
        cli_args = spec.get("cli_args") or []

        # Fallback to legacy start_cmd if present
        if not agent_type:
            legacy_cmd = str(spec.get("start_cmd") or "").strip()
            if legacy_cmd:
                return legacy_cmd
            raise ValueError("missing agent_type or start_cmd")

        # Resolve CLI binary: cli_type takes priority over agent_type
        if cli_type in ("claude", "claude_code"):
            cmd = "claude"
            use_claude_cli = True
        elif cli_type == "native":
            cmd = agent_type
            use_claude_cli = False
        else:
            # Backward compatible: infer from agent_type
            if agent_type == "codex":
                cmd = "codex"
                use_claude_cli = False
            elif agent_type in (
                "claude",
                "kimi",
                "minimax",
                "chatgpt",
                "gemini",
                "openai",
                "copilot",
                "alibaba",
                "bytedance",
            ):
                cmd = "claude"
                use_claude_cli = True
            else:
                cmd = agent_type
                use_claude_cli = False

        parts = [cmd]

        # Add model parameter (only if explicitly specified)
        if use_claude_cli and model:
            parts += ["--model", model]
        elif not use_claude_cli and model and agent_type in ("kimi", "gemini"):
            parts += ["--model", model]

        # KIMI-specific: MCP config file and subcommand
        if agent_type == "kimi" and not use_claude_cli:
            if cwd:
                parts += ["--mcp-config-file", f"{cwd}/.kimi/mcp.json"]
            kimi_subcommand = spec.get("kimi_subcommand")
            if kimi_subcommand is None:
                parts.append("acp")
            else:
                sub = str(kimi_subcommand).strip()
                if sub:
                    parts.append(sub)

        # Add CLI arguments
        if isinstance(cli_args, list):
            for arg in cli_args:
                parts.append(str(arg).strip())

        # Add initial prompt if specified (shell-escaped)
        # Only for Claude CLI; skip for KIMI native
        initial_prompt = str(spec.get("initial_prompt") or "").strip()
        if initial_prompt and use_claude_cli:
            escaped = initial_prompt.replace("'", "'\"'\"'")
            parts.append(f"'{escaped}'")

        return " ".join(parts)

    def _build_env_string(self, spec: dict[str, Any]) -> str:
        """Build inline environment variable prefix (VAR=val) for tmux command."""
        cwd = str(spec.get("cwd") or spec.get("path") or "").strip()
        manifest = _load_runtime_manifest(cwd) if cwd else None
        runtime = manifest.get("runtime") if isinstance(manifest, dict) else None
        env_spec = (runtime.get("env") or {}) if isinstance(runtime, dict) and isinstance(runtime.get("env"), dict) else (spec.get("env") or {})
        if not isinstance(env_spec, dict):
            return ""

        env_parts = []
        for key, value in env_spec.items():
            key = str(key).strip()
            value = str(value).strip()
            if not key:
                continue
            # Expand ${VAR} from current environment
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                value = os.environ.get(var_name, "") or self._lookup_secret(var_name)
            env_parts.append(f"{key}={value}")

        return " ".join(env_parts)

    def _build_export_string(self, spec: dict[str, Any]) -> str:
        """Build export environment variable string (export VAR=val) for tmux command."""
        cwd = str(spec.get("cwd") or spec.get("path") or "").strip()
        manifest = _load_runtime_manifest(cwd) if cwd else None
        export_spec = {} if manifest else (spec.get("export_cmd") or {})
        if not isinstance(export_spec, dict):
            return ""

        export_parts = []
        for key, value in export_spec.items():
            key = str(key).strip()
            value = str(value).strip()
            if not key:
                continue
            # Expand ${VAR} from current environment
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                value = os.environ.get(var_name, "") or self._lookup_secret(var_name)
            export_parts.append(f"{key}={value}")

        if not export_parts:
            return ""
        return "export " + " ".join(export_parts)

    @staticmethod
    def _lookup_secret(var_name: str) -> str:
        if not _SECRETS_FILE.exists():
            return ""
        try:
            for line in _SECRETS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == var_name:
                    return value.strip()
        except Exception:
            return ""
        return ""

    def _ensure_codex_auth_symlink(self, codex_home: str) -> None:
        """Symlink global auth.json into per-agent CODEX_HOME if missing."""
        global_auth = Path.home() / ".codex" / "auth.json"
        local_auth = Path(codex_home) / "auth.json"
        if local_auth.exists() or local_auth.is_symlink():
            return
        if not global_auth.exists():
            return
        try:
            Path(codex_home).mkdir(parents=True, exist_ok=True)
            local_auth.symlink_to(global_auth)
            self._log_event("codex_auth_symlinked", {"from": str(global_auth), "to": str(local_auth)})
        except Exception as e:
            self._log_event("codex_auth_symlink_failed", {"error": str(e)})

    def _setup_mcp_config(self, spec: dict[str, Any]) -> None:
        """Setup MCP config file for agent based on agent_type.

        Delegates to shared config_generator module.
        """
        agent_name = str(spec.get("name") or "").strip()
        if not agent_name:
            return

        try:
            result = _generate_all_configs(spec)
            self._log_event("mcp_config_setup", {
                "agent_name": agent_name,
                "agent_type": str(spec.get("agent_type") or "").strip(),
                "cwd": str(spec.get("cwd") or "").strip(),
                "mcp_config": result.get("mcp_config", False),
                "claude_md": result.get("claude_md"),
            })
        except Exception as e:
            self._log_event("mcp_config_error", {"agent_name": agent_name, "error": str(e)})

    # ------------------------------------------------------------------
    # G-GATE-MEMORY-PERSIST implementation
    # Spec: /xkagent_infra/brain/base/spec/policies/memory/persistence.yaml
    # ------------------------------------------------------------------
    _MEMORY_ROOT = Path("/xkagent_infra/runtime/memory")

    def _setup_memory_capture(self, agent_name: str, tmux_session: str) -> None:
        """Configure tmux pipe-pane to capture agent session output.

        Directory layout: /xkagent_infra/runtime/memory/{date}/{agent_name}/
        File: {tmux_session}_{HHMMSS}.log
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            agent_dir = self._MEMORY_ROOT / today / agent_name
            agent_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%H%M%S")
            log_file = agent_dir / f"{tmux_session}_{ts}.log"

            # Enable pipe-pane: strip ANSI escape codes, add timestamp prefix, then append to log file
            strip_cmd = (
                f"sed 's/\\x1B\\[[0-9;?]*[mGKHFJABCDlh]//g; s/\\x1B//g'"
                f" | awk '{{print strftime(\"[%Y-%m-%d %H:%M:%S]\"), $0; fflush()}}'"
                f" >> '{log_file}'"
            )
            p = subprocess.run(
                ["tmux", "pipe-pane", "-t", tmux_session, "-o", strip_cmd],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if p.returncode == 0:
                self._log_event("memory_capture_started", {
                    "agent_name": agent_name,
                    "tmux_session": tmux_session,
                    "log_file": str(log_file),
                })
            else:
                self._log_event("memory_capture_failed", {
                    "agent_name": agent_name,
                    "error": (p.stderr or "").strip(),
                })

            # Update 'latest' symlink
            latest = self._MEMORY_ROOT / "latest"
            today_dir = self._MEMORY_ROOT / today
            try:
                if latest.is_symlink() or latest.exists():
                    latest.unlink()
                latest.symlink_to(today)
            except OSError:
                pass  # Non-critical

        except Exception as e:
            # Memory capture failure must not block agent start
            self._log_event("memory_capture_error", {
                "agent_name": agent_name,
                "error": str(e),
            })

    def restart(self, agent_name: str, reason: str) -> RestartResult:
        spec = self._get_agent_spec()
        spec = spec.get(agent_name)
        if not spec:
            return RestartResult(False, agent_name, reason, 0, error=f"Unknown agent: {agent_name}")

        tmux_session = str(spec.get("tmux_session") or "").strip()
        cwd = str(spec.get("cwd") or spec.get("path") or "").strip() or None

        if not tmux_session:
            return RestartResult(False, agent_name, reason, 0, error="missing tmux_session")

        try:
            start_cmd = self._build_start_command(spec)
        except ValueError as e:
            return RestartResult(False, agent_name, reason, 0, error=str(e))

        # Setup MCP config before starting agent
        try:
            self._setup_mcp_config(spec)
        except Exception as e:
            self._log_event("mcp_config_error", {"agent_name": agent_name, "error": str(e)})
            # Continue anyway, MCP config failure shouldn't block agent start

        # Build full shell command: "cd /path && export VAR=val && VAR2=val2 command"
        env_inline = self._build_env_string(spec)      # env: inline format (VAR=val cmd)
        env_export = self._build_export_string(spec)   # export_cmd: export format (export VAR=val &&)

        shell_parts = []
        if cwd:
            shell_parts.append(f"cd {shlex.quote(cwd)}")
        if env_export:
            shell_parts.append(env_export)

        # Export tmux identity vars so MCP servers can detect session/pane
        # even when the parent process (e.g. Codex) strips TMUX env vars
        shell_parts.append(f"export TMUX_SESSION={tmux_session}")
        shell_parts.append("export TMUX_PANE=$(tmux display-message -p '#{pane_id}' 2>/dev/null)")

        # For Codex agents, set CODEX_HOME to per-agent config directory
        # and symlink global auth.json so per-agent dir shares authentication
        # For Kimi agents, set KIMI_HOME similarly
        agent_type = str(spec.get("agent_type") or "").strip()
        if agent_type == "codex" and cwd:
            codex_home = f"{cwd}/.codex"
            shell_parts.append(f"export CODEX_HOME={codex_home}")
            self._ensure_codex_auth_symlink(codex_home)
        elif agent_type == "kimi" and cwd:
            kimi_home = f"{cwd}/.kimi"
            shell_parts.append(f"export KIMI_HOME={kimi_home}")

        # Build final command: "VAR=val cmd" (inline env vars)
        if env_inline:
            shell_parts.append(f"{env_inline} {start_cmd}")
        else:
            shell_parts.append(start_cmd)

        full_shell_cmd = " && ".join(shell_parts)

        if agent_name not in self._agent_states:
            self._agent_states[agent_name] = AgentState(name=agent_name, tmux_session=tmux_session)

        state = self._agent_states[agent_name]
        can_restart, check_reason = self._should_restart(agent_name)
        if not can_restart:
            self._log_event("agent_restart_skipped", {"agent_name": agent_name, "reason": reason, "skip_reason": check_reason})
            return RestartResult(False, agent_name, reason, len(state.restart_attempts), error=check_reason)

        now = time.time()
        state.restart_attempts.append(now)
        attempt = len(state.restart_attempts)

        self._log_event("agent_restart_attempt", {"agent_name": agent_name, "reason": reason, "attempt": attempt, "tmux_session": tmux_session, "cmd": full_shell_cmd})

        try:
            sessions = self._get_tmux_sessions()
            if tmux_session in sessions:
                subprocess.run(["tmux", "kill-session", "-t", tmux_session], capture_output=True, text=True, timeout=10, check=False)

            cmd = ["tmux", "new-session", "-d", "-s", tmux_session]
            if cwd:
                cmd += ["-c", cwd]
            cmd.append(full_shell_cmd)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
            if p.returncode != 0:
                raise RuntimeError((p.stderr or p.stdout or "").strip() or "tmux new-session failed")

            # G-GATE-MEMORY-PERSIST: 启动后立即配置 tmux pipe-pane 捕获
            self._setup_memory_capture(agent_name, tmux_session)

            state.last_restart = now
            backoff = self._calculate_backoff(attempt)
            state.cooldown_until = now + backoff
            self._log_event("agent_restart_success", {"agent_name": agent_name, "reason": reason, "attempt": attempt, "next_allowed_in": backoff})
            return RestartResult(True, agent_name, reason, attempt)
        except Exception as e:
            self._log_event("agent_restart_failed", {"agent_name": agent_name, "reason": reason, "attempt": attempt, "error": str(e)})
            return RestartResult(False, agent_name, reason, attempt, error=str(e))

    def reconcile(self) -> list[RestartResult]:
        """Ensure required/running agents are up."""
        spec = self._get_agent_spec()
        online = self._get_online_agents()
        sessions = self._get_tmux_sessions()
        results: list[RestartResult] = []

        for name, spec in spec.items():
            if name == self.self_name:
                continue

            desired_state = str(spec.get("desired_state") or "running").strip().lower()
            required = bool(spec.get("required", False))
            status = str(spec.get("status") or "active").strip().lower()

            should_run = (desired_state == "running") or required
            if not should_run:
                continue
            if status == "inactive" and not required and desired_state != "running":
                continue

            tmux_session = str(spec.get("tmux_session") or "").strip()
            is_online = name in online
            session_exists = tmux_session in sessions if tmux_session else False

            if not is_online:
                # If tmux session exists, agent might still be initializing MCP
                # Skip restart to give it time to send heartbeat
                if session_exists:
                    self._log_event("agent_initializing", {
                        "agent_name": name,
                        "tmux_session": tmux_session,
                        "reason": "session_exists_but_not_online"
                    })
                    continue
                results.append(self.restart(name, reason="session_missing"))

        return results
