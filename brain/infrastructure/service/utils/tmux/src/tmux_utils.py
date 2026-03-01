#!/usr/bin/env python3
"""
tmux 封装工具集 - 所有 tmux 操作的统一入口

G-GATE-TMUX-PROXY: 禁止 agent 直接调用 tmux 命令，
所有操作必须通过 brain_tmux_api 统一入口执行。

已封装操作:
  - list_sessions()    → tmux list-sessions
  - has_session(name)  → tmux has-session
  - capture_pane(target, lines) → tmux capture-pane
  - list_panes(session) → tmux list-panes
  - display_message(target, fmt) → tmux display-message
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from audit_log import agent_name_env, build_record, dual_write, session_name_env


def _tmux(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _audit(tool_name: str, tool_input: dict) -> None:
    """Write audit record."""
    try:
        rec = build_record(
            tool_name=tool_name,
            tool_input=tool_input,
            agent=agent_name_env(),
            session=session_name_env(),
            type_="command",
        )
        dual_write(rec)
    except Exception:
        pass  # audit failure should never block operations


@dataclass
class TmuxSession:
    name: str
    attached: bool
    windows: int


def list_sessions() -> list[TmuxSession]:
    """List all tmux sessions."""
    _audit("TMUX_LIST_SESSIONS", {})
    try:
        result = _tmux(
            "list-sessions", "-F", "#{session_name}:#{session_attached}:#{session_windows}",
            check=False,
        )
        if result.returncode != 0:
            return []
        sessions = []
        for line in (result.stdout or "").strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                sessions.append(TmuxSession(
                    name=parts[0],
                    attached=parts[1] == "1",
                    windows=int(parts[2]) if parts[2].isdigit() else 1,
                ))
        return sessions
    except Exception:
        return []


def has_session(name: str) -> bool:
    """Check if a tmux session exists."""
    _audit("TMUX_HAS_SESSION", {"session": name})
    result = _tmux("has-session", "-t", name, check=False)
    return result.returncode == 0


def capture_pane(target: str, lines: int = 200) -> str:
    """Capture pane content.

    Args:
        target: tmux target (session:window.pane or %pane_id)
        lines: number of history lines to capture (default 200)

    Returns:
        Captured text content
    """
    _audit("TMUX_CAPTURE_PANE", {"target": target, "lines": lines})
    try:
        result = _tmux(
            "capture-pane", "-t", target, "-p", "-S", f"-{lines}",
            check=False,
        )
        return (result.stdout or "").rstrip()
    except Exception as e:
        return f"error: {e}"


@dataclass
class TmuxPane:
    pane_id: str
    session: str
    window: str
    command: str
    active: bool


def list_panes(session: Optional[str] = None) -> list[TmuxPane]:
    """List panes, optionally filtered by session.

    Args:
        session: session name to filter (None = all sessions)
    """
    _audit("TMUX_LIST_PANES", {"session": session or "all"})
    try:
        args = ["list-panes", "-F", "#{pane_id}:#{session_name}:#{window_index}:#{pane_current_command}:#{pane_active}"]
        if session:
            args.extend(["-t", session])
        else:
            args.append("-a")
        result = _tmux(*args, check=False)
        if result.returncode != 0:
            return []
        panes = []
        for line in (result.stdout or "").strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 5:
                panes.append(TmuxPane(
                    pane_id=parts[0],
                    session=parts[1],
                    window=parts[2],
                    command=parts[3],
                    active=parts[4] == "1",
                ))
        return panes
    except Exception:
        return []


def display_message(target: str, fmt: str = "#{pane_id}") -> str:
    """Run tmux display-message and return output.

    Args:
        target: tmux target
        fmt: format string (default: pane_id)

    Returns:
        Output string
    """
    _audit("TMUX_DISPLAY_MESSAGE", {"target": target, "fmt": fmt})
    try:
        result = _tmux("display-message", "-t", target, "-p", fmt, check=False)
        return (result.stdout or "").strip()
    except Exception as e:
        return f"error: {e}"
