#!/usr/bin/env python3
"""
Audit Log Engine (shared runtime module)

SSOT for audit logging. Intended to be called by:
- Claude hooks (.claude/hooks/*) wrappers
- Human/agent command wrappers (brain_exec)
- Any other agent integration

Dual-write targets (when scope can be inferred):
- Global (LEP): /brain/runtime/logs/agents/global_agent_log_{YYYY-MM-DD}.jsonl
- Global legacy: /brain/runtime/memory/agents/global_agent_log_{YYYY-MM-DD}.jsonl
- Group: /brain/groups/{group}/memory/group_activity_{YYYY-MM-DD}.jsonl
- Project (legacy): /brain/groups/{group}/projects/{project}/memory/execution_logs/{YYYY-MM-DD}.jsonl
- Project (LEP): /brain/groups/{group}/projects/{project}/logs/{YYYY-MM-DD}.jsonl
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fcntl
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")

GLOBAL_LOG_DIR = Path("/brain/runtime/logs/agents")
GLOBAL_LEGACY_DIR = Path("/brain/runtime/memory/agents")


@dataclass(frozen=True)
class Scope:
    group: str | None
    project: str | None

    @property
    def scope_str(self) -> str:
        if self.group and self.project:
            return f"{self.group}/{self.project}"
        if self.group:
            return self.group
        return "global"


def iso_ts() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def today_ymd() -> str:
    return datetime.now(TZ).date().isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    ensure_parent(path)
    lock_path = Path(str(path) + ".lock")
    ensure_parent(lock_path)

    line = json.dumps(record, ensure_ascii=False)
    with open(lock_path, "a", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


_SCOPE_RE = re.compile(r"/brain/groups/([^/]+)/projects/([^/]+)/")
_GROUP_RE = re.compile(r"/brain/groups/([^/]+)/")
_APP_SCOPE_RE = re.compile(r"/app/groups/([^/]+)/[^/]+/domain/([^/]+)/")


def infer_scope_from_text(text: str) -> Scope:
    if not text:
        return Scope(group=None, project=None)

    m = _SCOPE_RE.search(text)
    if m:
        return Scope(group=m.group(1), project=m.group(2))

    m = _APP_SCOPE_RE.search(text)
    if m:
        return Scope(group=m.group(1), project=m.group(2))

    m = _GROUP_RE.search(text)
    if m:
        return Scope(group=m.group(1), project=None)

    return Scope(group=None, project=None)


def infer_scope(tool_input: dict[str, Any]) -> Scope:
    fp = tool_input.get("file_path") or ""
    if fp:
        return infer_scope_from_text(str(fp))

    cmd = tool_input.get("command") or ""
    if cmd:
        return infer_scope_from_text(str(cmd))

    try:
        return infer_scope_from_text(json.dumps(tool_input, ensure_ascii=False))
    except Exception:
        return infer_scope_from_text(str(tool_input))


def truncate(s: str, limit: int = 2000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "...(truncated)"


def summarize(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "Bash":
        cmd = str(tool_input.get("command") or "")
        out: dict[str, Any] = {"command": truncate(cmd, 2000)}
        if "exit_code" in tool_input:
            try:
                out["exit_code"] = int(tool_input.get("exit_code"))
            except Exception:
                out["exit_code"] = tool_input.get("exit_code")
        return out

    if tool_name in {"Write", "Edit"}:
        fp = str(tool_input.get("file_path") or "")
        content = tool_input.get("content")
        new_string = tool_input.get("new_string")
        old_string = tool_input.get("old_string")
        approx = None
        for v in (content, new_string, old_string):
            if isinstance(v, str):
                approx = len(v)
                break
        return {"file_path": fp, "content_len": approx}

    try:
        return {"tool_input": truncate(json.dumps(tool_input, ensure_ascii=False), 2000)}
    except Exception:
        return {"tool_input": truncate(str(tool_input), 2000)}


def build_record(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    agent: str,
    session: str,
    type_: str = "command",
    ts: str | None = None,
) -> dict[str, Any]:
    scope = infer_scope(tool_input)
    record: dict[str, Any] = {
        "ts": ts or iso_ts(),
        "agent": agent,
        "session": session,
        "type": type_,
        "scope": scope.scope_str,
        "tool": tool_name,
        **summarize(tool_name, tool_input),
    }
    return record


def append_text(path: Path, text: str) -> None:
    """Append text to a file with locking."""
    ensure_parent(path)
    lock_path = Path(str(path) + ".lock")
    ensure_parent(lock_path)

    with open(lock_path, "a", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def format_terminal_line(record: dict[str, Any]) -> str:
    """Format a record as human-readable terminal log line."""
    ts = record.get("ts", "")
    agent = record.get("agent", "")
    tool = record.get("tool", "")
    scope = record.get("scope", "")

    # Extract key info based on tool type
    detail = ""
    if tool == "Bash":
        cmd = record.get("command", "")
        if len(cmd) > 100:
            cmd = cmd[:100] + "..."
        detail = f"$ {cmd}"
    elif tool in {"Write", "Edit"}:
        fp = record.get("file_path", "")
        content_len = record.get("content_len", "?")
        detail = f"{fp} ({content_len} chars)"
    else:
        ti = record.get("tool_input", "")
        if len(ti) > 100:
            ti = ti[:100] + "..."
        detail = ti

    return f"[{ts}] {agent} | {tool} | {scope} | {detail}"


def dual_write(record: dict[str, Any], *, scope: str | None = None, ymd: str | None = None) -> None:
    ymd = ymd or today_ymd()
    scope_str = scope or record.get("scope") or "global"
    session = record.get("session", "")

    # Global (LEP)
    try:
        append_jsonl(GLOBAL_LOG_DIR / f"global_agent_log_{ymd}.jsonl", record)
    except Exception:
        pass

    # Global legacy
    try:
        append_jsonl(GLOBAL_LEGACY_DIR / f"global_agent_log_{ymd}.jsonl", record)
    except Exception:
        pass

    # Terminal log (human-readable, per-session)
    if session:
        try:
            # Sanitize session name for filename
            safe_session = re.sub(r'[^\w\-]', '_', session)
            terminal_line = format_terminal_line(record)
            append_text(GLOBAL_LOG_DIR / f"{safe_session}_{ymd}.txt", terminal_line)
        except Exception:
            pass

    # Group/Project (best effort)
    if "/" in scope_str:
        group, project = scope_str.split("/", 1)
    else:
        group, project = (scope_str, None) if scope_str not in {"global", ""} else (None, None)

    if group:
        try:
            append_jsonl(Path(f"/brain/groups/{group}/memory/group_activity_{ymd}.jsonl"), record)
        except Exception:
            pass

    if group and project:
        try:
            append_jsonl(
                Path(f"/brain/groups/{group}/projects/{project}/memory/execution_logs/{ymd}.jsonl"),
                record,
            )
        except Exception:
            pass
        try:
            append_jsonl(Path(f"/brain/groups/{group}/projects/{project}/logs/{ymd}.jsonl"), record)
        except Exception:
            pass


def agent_name_env() -> str:
    # Prefer explicit identifiers
    explicit = os.environ.get("AGENT_NAME") or os.environ.get("CODEX_AGENT") or os.environ.get("CLAUDE_AGENT")
    if explicit:
        return explicit

    # Codex harness hint
    if os.environ.get("CODEX_CI") or os.environ.get("CODEX_MANAGED_BY_NPM"):
        return "codex"

    # Infer from session naming conventions (tmux sessions like claude_*, codex_*, gemini_*)
    sess = os.environ.get("TMUX_SESSION") or os.environ.get("SESSION") or os.environ.get("CLAUDE_SESSION")
    if not sess and os.environ.get("TMUX"):
        try:
            out = subprocess.check_output(["tmux", "display-message", "-p", "#S"], stderr=subprocess.DEVNULL)
            sess = out.decode("utf-8", errors="ignore").strip() or None
        except Exception:
            sess = None
    if sess:
        s = sess.lower()
        if s.startswith("claude") or s.startswith("claude_"):
            return "claude"
        if s.startswith("codex") or s.startswith("codex_"):
            return "codex"
        if s.startswith("gemini") or s.startswith("gemini_"):
            return "gemini"

    # Fall back to local user
    return os.environ.get("USER") or os.environ.get("LOGNAME") or "agent"


def session_name_env() -> str:
    explicit = os.environ.get("TMUX_SESSION") or os.environ.get("SESSION") or os.environ.get("CLAUDE_SESSION")
    if explicit:
        return explicit

    # If we're inside tmux, infer session name.
    if os.environ.get("TMUX"):
        try:
            out = subprocess.check_output(["tmux", "display-message", "-p", "#S"], stderr=subprocess.DEVNULL)
            sess = out.decode("utf-8", errors="ignore").strip()
            if sess:
                return sess
        except Exception:
            pass

    # Fall back to a stable-ish identifier.
    host = os.uname().nodename
    pid = os.getpid()
    return f"{host}:{pid}"


__all__ = [
    "Scope",
    "agent_name_env",
    "append_jsonl",
    "append_text",
    "build_record",
    "dual_write",
    "format_terminal_line",
    "infer_scope",
    "infer_scope_from_text",
    "iso_ts",
    "session_name_env",
    "today_ymd",
    "truncate",
]
