#!/usr/bin/env python3
"""
PMO one-shot dispatch wrapper for task_manager hard gate.

Flow:
1) PROJECT_DEPENDENCY_SET
2) TASK_STATS
3) TASK_PIPELINE_CHECK (must be valid=true)
4) TASK_UPDATE -> in_progress (unless --precheck-only)
"""

import argparse
import json
import socket
import sys
import time
import uuid
from typing import Dict, Iterable, List, Optional, Tuple


def daemon_call(sock_path: str, action: str, data: dict) -> dict:
    req = {"action": action, "data": data}
    raw = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(8.0)
    s.connect(sock_path)
    s.sendall(raw)
    buf = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
        if b"\n" in buf:
            break
    s.close()
    if not buf:
        raise RuntimeError(f"empty daemon response for action={action}")
    return json.loads(buf.decode("utf-8"))


def register_requester(sock_path: str, requester: str) -> None:
    daemon_call(sock_path, "service_register", {"service_name": requester, "metadata": {"role": "pmo"}})


def send_event(
    sock_path: str,
    from_agent: str,
    to_service: str,
    conversation_id: str,
    event_type: str,
    data: dict,
) -> None:
    daemon_call(
        sock_path,
        "ipc_send",
        {
            "from": from_agent,
            "to": to_service,
            "conversation_id": conversation_id,
            "payload": {"event_type": event_type, "data": data},
        },
    )


def wait_for_events(
    sock_path: str,
    agent: str,
    conversation_id: str,
    event_types: Iterable[str],
    timeout_s: int,
) -> Tuple[str, dict]:
    expected = set(event_types)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = daemon_call(
            sock_path,
            "ipc_recv",
            {"agent": agent, "ack_mode": "manual", "max_items": 50},
        )
        msgs = resp.get("messages", [])
        ack_ids: List[str] = []
        chosen: Optional[Tuple[str, dict]] = None
        for m in msgs:
            msg_id = m.get("msg_id")
            if msg_id:
                ack_ids.append(msg_id)
            if m.get("conversation_id") != conversation_id:
                continue
            payload = m.get("payload", {})
            ev = payload.get("event_type")
            if ev in expected and chosen is None:
                chosen = (ev, payload)
        if ack_ids:
            daemon_call(sock_path, "ipc_ack", {"agent": agent, "msg_ids": ack_ids})
        if chosen is not None:
            return chosen
        time.sleep(0.2)
    raise TimeoutError(f"timeout waiting events={sorted(expected)} conversation_id={conversation_id}")


def flatten_dep_args(dep_args: List[str]) -> List[str]:
    out: List[str] = []
    for raw in dep_args:
        for item in raw.split(","):
            dep = item.strip()
            if dep:
                out.append(dep)
    dedup: List[str] = []
    seen = set()
    for dep in out:
        if dep in seen:
            continue
        seen.add(dep)
        dedup.append(dep)
    return dedup


def payload_errors(payload: Dict) -> str:
    errs = payload.get("errors") or []
    if isinstance(errs, list):
        return "; ".join(str(e) for e in errs)
    return str(errs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PMO one-shot wrapper: dependencies + stats + pipeline check + dispatch."
    )
    parser.add_argument("--socket", default="/tmp/brain_ipc.sock")
    parser.add_argument("--service-name", default="service-task_manager")
    parser.add_argument("--requester", required=True, help="PMO agent/service name")
    parser.add_argument("--project-id", required=True, help="Project/spec id")
    parser.add_argument("--group", default="", help="Optional task group filter")
    parser.add_argument("--task-id", default="", help="Task to move into in_progress")
    parser.add_argument(
        "--depends-on",
        action="append",
        default=[],
        help="Upstream project dependencies (repeatable or comma-separated)",
    )
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--precheck-only", action="store_true", help="Run 3 checks only, do not dispatch")
    parser.add_argument(
        "--register-requester",
        action="store_true",
        help="Register requester via service_register before sending events",
    )
    args = parser.parse_args()

    if not args.precheck_only and not args.task_id:
        print("error: --task-id is required unless --precheck-only is set", file=sys.stderr)
        return 2

    if args.register_requester:
        register_requester(args.socket, args.requester)

    deps = flatten_dep_args(args.depends_on)
    conv_id = str(uuid.uuid4())
    summary: Dict[str, object] = {
        "project_id": args.project_id,
        "task_id": args.task_id or None,
        "depends_on": deps,
    }

    send_event(
        args.socket,
        args.requester,
        args.service_name,
        conv_id,
        "PROJECT_DEPENDENCY_SET",
        {"project_id": args.project_id, "depends_on": deps, "updated_by": args.requester},
    )
    ev, payload = wait_for_events(
        args.socket,
        args.requester,
        conv_id,
        ["PROJECT_DEPENDENCY_UPDATED", "TASK_REJECTED", "UNKNOWN_EVENT"],
        args.timeout,
    )
    if ev != "PROJECT_DEPENDENCY_UPDATED" or payload.get("status") != "ok":
        print(f"PROJECT_DEPENDENCY_SET failed: {payload_errors(payload)}", file=sys.stderr)
        return 3
    summary["dependency"] = payload.get("data", {})

    stats_data = {"project_id": args.project_id}
    if args.group:
        stats_data["group"] = args.group
    send_event(
        args.socket,
        args.requester,
        args.service_name,
        conv_id,
        "TASK_STATS",
        stats_data,
    )
    ev, payload = wait_for_events(
        args.socket,
        args.requester,
        conv_id,
        ["TASK_STATS_RESULT", "TASK_REJECTED", "UNKNOWN_EVENT"],
        args.timeout,
    )
    if ev != "TASK_STATS_RESULT" or payload.get("status") != "ok":
        print(f"TASK_STATS failed: {payload_errors(payload)}", file=sys.stderr)
        return 4
    summary["stats"] = payload.get("data", {})

    pipeline_data = {"project_id": args.project_id}
    if args.group:
        pipeline_data["group"] = args.group
    send_event(
        args.socket,
        args.requester,
        args.service_name,
        conv_id,
        "TASK_PIPELINE_CHECK",
        pipeline_data,
    )
    ev, payload = wait_for_events(
        args.socket,
        args.requester,
        conv_id,
        ["TASK_PIPELINE_RESULT", "TASK_REJECTED", "UNKNOWN_EVENT"],
        args.timeout,
    )
    if ev != "TASK_PIPELINE_RESULT" or payload.get("status") != "ok":
        print(f"TASK_PIPELINE_CHECK failed: {payload_errors(payload)}", file=sys.stderr)
        return 5
    pipe = payload.get("data", {})
    summary["pipeline"] = pipe
    if not pipe.get("valid", False):
        print("TASK_PIPELINE_CHECK is not valid; dispatch aborted.", file=sys.stderr)
        print(json.dumps(pipe, ensure_ascii=False, indent=2), file=sys.stderr)
        return 6

    if args.precheck_only:
        print(json.dumps({"status": "ok", "mode": "precheck_only", "summary": summary}, ensure_ascii=False, indent=2))
        return 0

    send_event(
        args.socket,
        args.requester,
        args.service_name,
        conv_id,
        "TASK_UPDATE",
        {"task_id": args.task_id, "status": "in_progress"},
    )
    ev, payload = wait_for_events(
        args.socket,
        args.requester,
        conv_id,
        ["TASK_UPDATED", "TASK_REJECTED", "UNKNOWN_EVENT"],
        args.timeout,
    )
    if ev != "TASK_UPDATED" or payload.get("status") != "ok":
        print(f"TASK_UPDATE(in_progress) failed: {payload_errors(payload)}", file=sys.stderr)
        return 7

    summary["dispatched"] = payload.get("data", {})
    print(json.dumps({"status": "ok", "mode": "dispatch", "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
