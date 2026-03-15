"""
BS-025-T12 集成验收：SC1-SC5
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


def run(coro, timeout=5):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))


def _write_project(
    projects_dir: str,
    project_id: str,
    *,
    status: str = "in_progress",
    start_time: str = "",
    check_interval: int = 1,
    timeout_duration: int = 3600,
    escalation_threshold: int = 2,
):
    proj_dir = os.path.join(projects_dir, project_id.lower())
    os.makedirs(proj_dir, exist_ok=True)
    data = {
        "project_id": project_id,
        "runtime": {
            "check_interval": check_interval,
            "timeout_duration": timeout_duration,
            "escalation_threshold": escalation_threshold,
            "qa_agent": "agent_qa",
            "orchestrator_agent": "agent_orch",
        },
        "agent_roster": [{"agent_name": "agent_dev", "role": "developer"}],
        "tasks": [
            {
                "id": "T1",
                "title": "Task 1",
                "status": status,
                "priority": "high",
                "assigned_to": "agent_dev",
                "start_time": start_time,
                "overdue_count": 0,
            }
        ],
    }
    yaml_path = os.path.join(proj_dir, "task_manager.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return yaml_path


def _make_send_recv_with_queue(messages):
    sent = []
    queue = list(messages)

    def send_fn(**kwargs):
        sent.append(kwargs)
        return {"msg_id": f"m-{len(sent)}"}

    def recv_fn(wait_seconds=30):
        if queue:
            return {"messages": [queue.pop(0)]}
        return {"messages": []}

    return send_fn, recv_fn, sent


def _make_ipc_msg(msg_id: str, event_type: str, project_id: str, task_id: str):
    return {
        "msg_id": msg_id,
        "payload": {
            "content": json.dumps(
                {
                    "event_type": event_type,
                    "project_id": project_id,
                    "task_id": task_id,
                },
                ensure_ascii=False,
            )
        },
    }


def _parse_event_type_from_send_call(call_kwargs):
    message = call_kwargs["message"]
    body = message.split("\n", 1)[1]
    return json.loads(body)["event_type"]


def test_sc1_crash_recovery_from_yaml(tmp_path, monkeypatch):
    """
    SC1: 不走 graceful shutdown，模拟异常退出后重启，状态从 YAML 恢复。
    """
    projects_dir = str(tmp_path / "projects")
    state_dir = str(tmp_path / "state")
    os.makedirs(projects_dir)
    yaml_path = _write_project(projects_dir, "BS-SC1", status="in_progress")

    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    send_fn, recv_fn, _ = _make_send_recv_with_queue([])

    async def first_run():
        e = Engine()
        e.inject_ipc(send_fn, recv_fn)
        await e._init_config_loader()
        await e._init_state_store()
        await e._init_fsm_engine()
        ok = await e._fsm_engine.trigger("BS-SC1", "T1", "submit")
        assert ok is True

    run(first_run())

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["tasks"][0]["status"] == "reviewing"

    async def second_run():
        e2 = Engine()
        e2.inject_ipc(send_fn, recv_fn)
        await e2._init_config_loader()
        await e2._init_state_store()
        await e2._init_fsm_engine()
        model = e2._fsm_engine.get_task("BS-SC1", "T1")
        assert model is not None
        assert model.state == "reviewing"

    run(second_run())


def test_sc2_overdue_emits_task_overdue_within_scan(tmp_path, monkeypatch):
    """
    SC2: ACTIVE 任务超时后，在扫描周期内发出 TASK_OVERDUE。
    """
    projects_dir = str(tmp_path / "projects")
    state_dir = str(tmp_path / "state")
    os.makedirs(projects_dir)
    start_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    _write_project(
        projects_dir,
        "BS-SC2",
        status="in_progress",
        start_time=start_time,
        check_interval=1,
        timeout_duration=10,
        escalation_threshold=2,
    )

    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    send_fn, recv_fn, sent = _make_send_recv_with_queue([])

    async def scenario():
        e = Engine()
        e.inject_ipc(send_fn, recv_fn)
        await e._init_config_loader()
        await e._init_state_store()
        await e._init_fsm_engine()
        await e._init_scheduler()
        try:
            scan_fn = e._task_scheduler._project_schedulers["BS-SC2"]._scan_fn
            await scan_fn()
        finally:
            e._task_scheduler.stop()

    run(scenario())

    assert sent, "expected at least one outbound IPC message"
    event_types = [_parse_event_type_from_send_call(c) for c in sent]
    assert "TASK_OVERDUE" in event_types


def test_sc3_e2e_task_completed_to_review_ready_and_yaml(tmp_path, monkeypatch):
    """
    SC3: TASK_COMPLETED IPC -> FSM 转换 -> YAML 更新 -> TASK_REVIEW_READY 发出。
    """
    projects_dir = str(tmp_path / "projects")
    state_dir = str(tmp_path / "state")
    os.makedirs(projects_dir)
    yaml_path = _write_project(projects_dir, "BS-SC3", status="in_progress")

    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    inbound = [_make_ipc_msg("msg-sc3", "TASK_COMPLETED", "BS-SC3", "T1")]
    send_fn, recv_fn, sent = _make_send_recv_with_queue(inbound)

    async def scenario():
        e = Engine()
        e.inject_ipc(send_fn, recv_fn)
        await e._init_config_loader()
        await e._init_state_store()
        await e._init_fsm_engine()
        await e._init_ipc_handler()
        await e._ipc_handler._recv_and_process()

    run(scenario())

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["tasks"][0]["status"] == "reviewing"

    event_types = [_parse_event_type_from_send_call(c) for c in sent]
    assert "TASK_REVIEW_READY" in event_types


def test_sc4_two_projects_isolation(tmp_path, monkeypatch):
    """
    SC4: 2 个项目并行运行，状态互不干扰。
    """
    projects_dir = str(tmp_path / "projects")
    state_dir = str(tmp_path / "state")
    os.makedirs(projects_dir)
    yaml_a = _write_project(projects_dir, "BS-SC4-A", status="in_progress")
    yaml_b = _write_project(projects_dir, "BS-SC4-B", status="in_progress")

    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    inbound = [_make_ipc_msg("msg-sc4", "TASK_COMPLETED", "BS-SC4-A", "T1")]
    send_fn, recv_fn, _ = _make_send_recv_with_queue(inbound)

    async def scenario():
        e = Engine()
        e.inject_ipc(send_fn, recv_fn)
        await e._init_config_loader()
        await e._init_state_store()
        await e._init_fsm_engine()
        await e._init_ipc_handler()
        await e._ipc_handler._recv_and_process()

    run(scenario())

    with open(yaml_a, encoding="utf-8") as f:
        data_a = yaml.safe_load(f)
    with open(yaml_b, encoding="utf-8") as f:
        data_b = yaml.safe_load(f)

    assert data_a["tasks"][0]["status"] == "reviewing"
    assert data_b["tasks"][0]["status"] == "in_progress"


def test_sc5_health_endpoint_and_runtime_logs(tmp_path, monkeypatch, caplog):
    """
    SC5: 健康检查可用，并记录状态转换/IPC 收发日志。
    """
    projects_dir = str(tmp_path / "projects")
    state_dir = str(tmp_path / "state")
    os.makedirs(projects_dir)
    _write_project(projects_dir, "BS-SC5", status="in_progress")

    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine
    from health import HealthServer

    inbound = [_make_ipc_msg("msg-sc5", "TASK_COMPLETED", "BS-SC5", "T1")]
    send_fn, recv_fn, _ = _make_send_recv_with_queue(inbound)

    async def scenario():
        e = Engine()
        e.inject_ipc(send_fn, recv_fn)
        await e._init_config_loader()
        await e._init_state_store()
        await e._init_fsm_engine()
        await e._init_scheduler()
        await e._init_ipc_handler()
        await e._ipc_handler._recv_and_process()
        e._task_scheduler.stop()
        server = HealthServer(port=0, engine=e)
        payload = server._build_payload()
        return payload

    with caplog.at_level(logging.INFO):
        payload = run(scenario())

    assert payload["status"] == "ok"
    assert "managed_projects" in payload
    assert "scheduler_running" in payload
    assert any("FSM trigger 'submit' OK" in r.message for r in caplog.records)
    assert any("IPC sent:" in r.message for r in caplog.records)
