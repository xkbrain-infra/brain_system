#!/usr/bin/env python3
import argparse
import json
import os
import socket
import time
import uuid


def daemon_call(sock_path: str, action: str, data: dict) -> dict:
    req = {"action": action, "data": data}
    raw = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5.0)
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


def wait_for_event(sock_path: str, agent: str, event_type: str, timeout_s: int = 15) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = daemon_call(
            sock_path,
            "ipc_recv",
            {"agent": agent, "ack_mode": "manual", "max_items": 20},
        )
        msgs = resp.get("messages", [])
        msg_ids = []
        found = None
        for m in msgs:
            msg_id = m.get("msg_id")
            if msg_id:
                msg_ids.append(msg_id)
            payload = m.get("payload", {})
            if payload.get("event_type") == event_type and found is None:
                found = payload
        if msg_ids:
            daemon_call(sock_path, "ipc_ack", {"agent": agent, "msg_ids": msg_ids})
        if found is not None:
            return found
        time.sleep(0.2)
    raise TimeoutError(f"timeout waiting event={event_type} for agent={agent}")


def wait_for_service(sock_path: str, service_name: str, timeout_s: int = 15) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = daemon_call(sock_path, "agent_list", {"include_offline": False})
        except Exception:
            time.sleep(0.2)
            continue
        for a in resp.get("agents", []):
            if a.get("name") == service_name and a.get("online") is True:
                return
        time.sleep(0.2)
    raise TimeoutError(f"service not online: {service_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/brain_ipc.sock")
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--requester", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--group", default="system")
    parser.add_argument("--spec-id", required=True)
    args = parser.parse_args()

    wait_for_service(args.socket, args.service_name, timeout_s=20)

    smoke_group = f"smoke{os.getpid()}"
    pmo_stub = f"agent_{smoke_group}_pmo"
    daemon_call(args.socket, "service_register", {"service_name": args.requester, "metadata": {}})
    daemon_call(args.socket, "service_register", {"service_name": args.owner, "metadata": {}})
    daemon_call(args.socket, "service_register", {"service_name": pmo_stub, "metadata": {}})

    task_id = f"{args.group.upper()}-SMOKE-T{int(time.time())}-{uuid.uuid4().hex[:6].upper()}"
    conversation_id = str(uuid.uuid4())
    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_CREATE",
                "data": {
                    "task_id": task_id,
                    "title": "smoke task",
                    "owner": args.owner,
                    "priority": "high",
                    "group": smoke_group,
                    "spec_id": args.spec_id,
                    "tags": ["knowledge-sync"],
                },
            },
        },
    )
    created = wait_for_event(args.socket, args.requester, "TASK_CREATED", timeout_s=15)
    assert created.get("status") == "ok", f"TASK_CREATED not ok: {created}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_UPDATE",
                "data": {"task_id": task_id, "status": "in_progress"},
            },
        },
    )
    updated = wait_for_event(args.socket, args.requester, "TASK_UPDATED", timeout_s=15)
    assert updated.get("status") == "ok", f"TASK_UPDATED not ok: {updated}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_UPDATE",
                "data": {"task_id": task_id, "status": "completed"},
            },
        },
    )
    updated2 = wait_for_event(args.socket, args.requester, "TASK_UPDATED", timeout_s=15)
    assert updated2.get("status") == "ok", f"TASK_UPDATED(complete) not ok: {updated2}"
    ks_task = wait_for_event(args.socket, pmo_stub, "KNOWLEDGE_SYNC_REQUEST", timeout_s=15)
    assert ks_task.get("data", {}).get("kind") == "task_completed", f"invalid sync kind: {ks_task}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "SPEC_CREATE",
                "data": {
                    "spec_id": args.spec_id,
                    "title": "smoke spec",
                    "group": args.group,
                    "owner": args.owner,
                },
            },
        },
    )
    spec_created = wait_for_event(args.socket, args.requester, "SPEC_CREATED", timeout_s=15)
    assert spec_created.get("status") == "ok", f"SPEC_CREATED not ok: {spec_created}"
    intake_task_id = spec_created.get("data", {}).get("intake_task_id")
    assert intake_task_id == f"{args.spec_id}-T001", f"unexpected intake task id: {spec_created}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_QUERY",
                "data": {"by": "spec", "spec_id": args.spec_id},
            },
        },
    )
    queried = wait_for_event(args.socket, args.requester, "TASK_QUERY_RESULT", timeout_s=15)
    tasks = queried.get("data", {}).get("tasks", [])
    assert any(t.get("task_id") == intake_task_id for t in tasks), f"intake task missing: {queried}"

    pipe_parent = f"{args.spec_id}-PIPE-A"
    pipe_child = f"{args.spec_id}-PIPE-B"
    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_CREATE",
                "data": {
                    "task_id": pipe_parent,
                    "title": "pipeline parent",
                    "owner": args.owner,
                    "priority": "normal",
                    "group": args.group,
                    "spec_id": args.spec_id,
                },
            },
        },
    )
    created_parent = wait_for_event(args.socket, args.requester, "TASK_CREATED", timeout_s=15)
    assert created_parent.get("status") == "ok", f"TASK_CREATED(parent) not ok: {created_parent}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_CREATE",
                "data": {
                    "task_id": pipe_child,
                    "title": "pipeline child",
                    "owner": args.owner,
                    "priority": "normal",
                    "group": args.group,
                    "spec_id": args.spec_id,
                    "status": "in_progress",
                    "depends_on": [pipe_parent],
                },
            },
        },
    )
    created_child = wait_for_event(args.socket, args.requester, "TASK_CREATED", timeout_s=15)
    assert created_child.get("status") == "ok", f"TASK_CREATED(child) not ok: {created_child}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_UPDATE",
                "data": {"task_id": pipe_child, "status": "in_progress"},
            },
        },
    )
    guard_reject = wait_for_event(args.socket, args.requester, "TASK_REJECTED", timeout_s=15)
    assert guard_reject.get("status") == "error", f"dispatch guard should reject before checks: {guard_reject}"

    upstream_project = f"{args.spec_id}-UPSTREAM"
    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "PROJECT_DEPENDENCY_SET",
                "data": {"project_id": args.spec_id, "depends_on": [upstream_project]},
            },
        },
    )
    dep_set = wait_for_event(args.socket, args.requester, "PROJECT_DEPENDENCY_UPDATED", timeout_s=15)
    assert dep_set.get("status") == "ok", f"PROJECT_DEPENDENCY_SET not ok: {dep_set}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_STATS",
                "data": {"spec_id": args.spec_id},
            },
        },
    )
    stats = wait_for_event(args.socket, args.requester, "TASK_STATS_RESULT", timeout_s=15)
    summary = stats.get("data", {}).get("summary", {})
    assert summary.get("total_tasks", 0) >= 4, f"TASK_STATS total_tasks too small: {stats}"
    assert summary.get("completed", 0) >= 1, f"TASK_STATS completed too small: {stats}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_PIPELINE_CHECK",
                "data": {"spec_id": args.spec_id},
            },
        },
    )
    pipeline_ready = wait_for_event(args.socket, args.requester, "TASK_PIPELINE_RESULT", timeout_s=15)
    ready_data = pipeline_ready.get("data", {})
    assert ready_data.get("valid") is True, f"TASK_PIPELINE_CHECK should pass before dispatch: {pipeline_ready}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_UPDATE",
                "data": {"task_id": pipe_child, "status": "in_progress"},
            },
        },
    )
    child_active = wait_for_event(args.socket, args.requester, "TASK_UPDATED", timeout_s=15)
    assert child_active.get("status") == "ok", f"TASK_UPDATE(child active) not ok: {child_active}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "TASK_PIPELINE_CHECK",
                "data": {"spec_id": args.spec_id},
            },
        },
    )
    pipeline = wait_for_event(args.socket, args.requester, "TASK_PIPELINE_RESULT", timeout_s=15)
    pdata = pipeline.get("data", {})
    assert pdata.get("valid") is False, f"TASK_PIPELINE_CHECK should detect flow issue: {pipeline}"
    assert pdata.get("flow_violations"), f"TASK_PIPELINE_CHECK missing violations: {pipeline}"

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "PROJECT_DEPENDENCY_QUERY",
                "data": {"project_id": args.spec_id},
            },
        },
    )
    dep_query = wait_for_event(args.socket, args.requester, "PROJECT_DEPENDENCY_RESULT", timeout_s=15)
    dep_data = dep_query.get("data", {})
    assert upstream_project in dep_data.get("depends_on", []), f"project dependency missing: {dep_query}"

    # Intake must already include a task-list artifact; S6 should advance directly.
    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "SPEC_PROGRESS",
                "data": {"spec_id": args.spec_id, "stage": "S6_tasks", "force": True},
            },
        },
    )
    s6 = wait_for_event(args.socket, args.requester, "SPEC_ADVANCED", timeout_s=15)
    assert s6.get("status") == "ok", f"S6 advance should succeed with intake task list: {s6}"

    spec_dir = f"/brain/groups/org/{args.group}/spec/{args.spec_id}"
    os.makedirs(spec_dir, exist_ok=True)
    with open(os.path.join(spec_dir, "06_tasks.yaml"), "w", encoding="utf-8") as f:
        f.write(
            "tasks:\n"
            f"  - task_id: \"{args.spec_id}-T001\"\n"
            "    title: \"smoke task item\"\n"
            f"    owner: {args.owner}\n"
            "    depends_on: []\n"
            "    acceptance_criteria:\n"
            "      - \"task has explicit owner\"\n"
        )

    daemon_call(
        args.socket,
        "ipc_send",
        {
            "from": args.requester,
            "to": args.service_name,
            "conversation_id": conversation_id,
            "payload": {
                "event_type": "SPEC_PROGRESS",
                "data": {"spec_id": args.spec_id, "stage": "archived", "force": True},
            },
        },
    )
    advanced = wait_for_event(args.socket, args.requester, "SPEC_ADVANCED", timeout_s=15)
    assert advanced.get("status") == "ok", f"SPEC_ADVANCED not ok: {advanced}"
    ks_spec = wait_for_event(args.socket, args.owner, "KNOWLEDGE_SYNC_REQUEST", timeout_s=15)
    assert ks_spec.get("data", {}).get("kind") == "spec_archived", f"invalid spec sync: {ks_spec}"

    assert os.path.isdir(spec_dir), f"spec dir not created: {spec_dir}"
    for required in ("00_index.yaml", "01_alignment.yaml", "08_complete.yaml"):
        path = os.path.join(spec_dir, required)
        assert os.path.exists(path), f"missing skeleton file: {path}"

    daemon_call(args.socket, "agent_unregister", {"instance_id": pmo_stub})
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
