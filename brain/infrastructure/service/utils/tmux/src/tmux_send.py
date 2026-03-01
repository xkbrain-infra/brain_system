#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# Add current directory to path for local imports
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from audit_log import agent_name_env, build_record, dual_write, session_name_env, truncate


def _tmux(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _ensure_target_exists(target: str) -> None:
    _tmux("display-message", "-t", target, "-p", "#{pane_id}", capture=True)

def _should_double_enter(target: str) -> bool:
    """Heuristic: some TUIs (notably Claude Code) require an extra Enter to submit."""
    try:
        cmd = (_tmux("display-message", "-t", target, "-p", "#{pane_current_command}", capture=True).stdout or "").strip()
    except Exception:
        return False

    # Detect known TUI programs by the running command (not by session name).
    # - "claude" is Claude Code TUI.
    # - "node" is often Codex CLI TUI wrapper in our setup.
    return cmd in {"claude", "node"}




def _send_message(
    target: str,
    message: str,
    *,
    clear_line: bool,
    double_enter: bool,
) -> None:
    # Best-effort TUI detection for safe "reset" keys.
    # Some TUIs treat Escape specially; we only send it when we detect a known TUI.
    is_claude_tui = False
    try:
        cmd = (_tmux("display-message", "-t", target, "-p", "#{pane_current_command}", capture=True).stdout or "").strip()
        # Detect known TUI programs by command, not by session name.
        is_claude_tui = cmd in {"claude", "node"}
    except Exception:
        pass

    lines = message.splitlines() or [""]
    first = True
    for line in lines:
        if clear_line and first:
            # Clear any modal state (e.g., Claude Code "review/bypass" UI) then clear input line.
            if is_claude_tui:
                _tmux("send-keys", "-t", target, "Escape")
                time.sleep(0.15)  # Let TUI settle after Escape
            _tmux("send-keys", "-t", target, "C-u")
            if is_claude_tui:
                time.sleep(0.1)  # Wait for line clear to take effect

        if line:
            _tmux("send-keys", "-t", target, "-l", line)
            time.sleep(0.05)  # Brief pause after text before Enter

        _tmux("send-keys", "-t", target, "C-m")
        first = False

    # Claude Code TUI requires extra Enter(s) to transition from
    # "input buffer" -> "submitted". Use C-m with adequate delays.
    if double_enter:
        time.sleep(0.15)
        _tmux("send-keys", "-t", target, "C-m")
        time.sleep(0.15)
        _tmux("send-keys", "-t", target, "C-m")
        time.sleep(0.1)


def _verify_visible(target: str, needle: str) -> bool:
    # Best-effort: Claude Code TUI may not echo input as a plain line.
    # We only treat it as a hint.
    try:
        out = _tmux("capture-pane", "-t", target, "-p", "-S", "-200", capture=True).stdout or ""
    except Exception:
        return False
    return needle in out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="brain_tmux_send", add_help=True)
    p.add_argument("-t", "--target", required=True, help="tmux target, e.g. session:window.pane or %pane_id")
    p.add_argument("--no-clear", action="store_true", help="do not send C-u before first line")
    p.add_argument(
        "--double-enter",
        action="store_true",
        help="send an extra Enter to submit (useful for some TUIs)",
    )
    p.add_argument(
        "--no-double-enter",
        action="store_true",
        help="do not send the extra Enter (even if auto-detected)",
    )
    p.add_argument("--verify", action="store_true", help="best-effort verify via capture-pane (may false-negative)")
    p.add_argument("--no-audit", action="store_true", help="do not write G-AUDIT record")
    p.add_argument("message", nargs="?", help="message string; if omitted, read from stdin")
    args = p.parse_args(argv)

    if args.message is None:
        if sys.stdin.isatty():
            p.error("message missing and stdin is a TTY")
        message = sys.stdin.read()
    else:
        message = args.message

    try:
        _ensure_target_exists(args.target)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        print(f"error: tmux target not found: {args.target}{(': ' + err) if err else ''}", file=sys.stderr)
        return 2

    msg_hash = hashlib.sha256(message.encode("utf-8", errors="ignore")).hexdigest()[:12]

    if not args.no_audit:
        rec = build_record(
            tool_name="TMUX_SEND",
            tool_input={
                "target": args.target,
                "clear_line": not args.no_clear,
                "message_len": len(message),
                "message_sha256_12": msg_hash,
                "message_preview": truncate(message, 300),
            },
            agent=agent_name_env(),
            session=session_name_env(),
            type_="command",
        )
        dual_write(rec)

    auto_double = _should_double_enter(args.target)
    double_enter = args.double_enter or (auto_double and not args.no_double_enter)
    _send_message(args.target, message, clear_line=not args.no_clear, double_enter=double_enter)

    if args.verify:
        time.sleep(0.25)
        needle = message[:80].strip()
        if needle and not _verify_visible(args.target, needle):
            print("warn: sent, but capture-pane verification did not find the message (may be normal).", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
