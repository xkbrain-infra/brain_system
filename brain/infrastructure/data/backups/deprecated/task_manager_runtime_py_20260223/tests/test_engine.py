"""
BS-025-T8 集成级验证：Engine
覆盖：组件初始化顺序、SIGTERM graceful shutdown、配置缺失启动失败
"""
import asyncio
import logging
import os
import signal
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_project(projects_dir: str, project_id: str) -> str:
    """在 projects_dir 下创建一个合法的项目目录和 task_manager.yaml。"""
    proj_dir = os.path.join(projects_dir, project_id.lower())
    os.makedirs(proj_dir, exist_ok=True)
    data = {
        "project_id": project_id,
        "runtime": {
            "check_interval": 60,
            "timeout_duration": 3600,
            "escalation_threshold": 2,
            "qa_agent": "agent_qa",
            "orchestrator_agent": "agent_orch",
        },
        "agent_roster": [
            {"agent_name": "agent_dev", "role": "developer"}
        ],
        "tasks": [
            {"id": "T1", "title": "Task 1", "status": "in_progress",
             "priority": "high", "assigned_to": "agent_dev"}
        ],
    }
    yaml_path = os.path.join(proj_dir, "task_manager.yaml")
    with open(yaml_path, "w") as f:
        yaml.dump(data, f, allow_unicode=True)
    return yaml_path


def run(coro, timeout=5):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


# ── 启动失败：TMR_PROJECTS_DIR 未设置 ────────────────────────────────────────

def test_startup_fails_without_projects_dir(monkeypatch):
    """TMR_PROJECTS_DIR 未设置时，启动应 sys.exit(1)。"""
    monkeypatch.delenv("TMR_PROJECTS_DIR", raising=False)
    monkeypatch.setenv("TMR_STATE_DIR", tempfile.mkdtemp())

    from engine import Engine
    engine = Engine()
    engine._projects_dir = ""  # 强制清空

    with pytest.raises(SystemExit) as exc_info:
        run(engine._init_config_loader())

    assert exc_info.value.code == 1


# ── ConfigLoader 初始化加载配置 ───────────────────────────────────────────────

def test_config_loader_init_loads_projects(tmp_path, monkeypatch):
    """_init_config_loader 加载有效项目配置。"""
    projects_dir = str(tmp_path / "projects")
    os.makedirs(projects_dir)
    _write_project(projects_dir, "BS-TEST")

    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine
    engine = Engine()

    run(engine._init_config_loader())

    assert len(engine._project_configs) == 1
    assert engine._project_configs[0].project_id == "BS-TEST"


# ── StateStore 初始化 ─────────────────────────────────────────────────────────

def test_state_store_init_creates_dir(tmp_path, monkeypatch):
    """_init_state_store 创建 state_dir 并加载 RuntimeState。"""
    state_dir = str(tmp_path / "new_state_dir")
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine
    engine = Engine()

    run(engine._init_state_store())

    assert os.path.isdir(state_dir)
    assert engine._runtime_state is not None


# ── FSMEngine 初始化恢复任务状态 ──────────────────────────────────────────────

def test_fsm_engine_restores_task_states(tmp_path, monkeypatch):
    """_init_fsm_engine 为 in_progress 任务恢复 FSM 实例。"""
    projects_dir = str(tmp_path / "projects")
    os.makedirs(projects_dir)
    _write_project(projects_dir, "BS-FSM")

    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine
    engine = Engine()
    engine.inject_ipc(MagicMock(return_value={"msg_id": "x"}), MagicMock())

    run(engine._init_config_loader())
    run(engine._init_state_store())
    run(engine._init_fsm_engine())

    # T1 状态为 in_progress，应恢复出 FSM 实例
    model = engine._fsm_engine.get_task("BS-FSM", "T1")
    assert model is not None
    assert model.state == "in_progress"


# ── Scheduler 初始化 ──────────────────────────────────────────────────────────

def test_scheduler_init_starts(tmp_path, monkeypatch):
    """_init_scheduler 启动后 scheduler.running = True。"""
    projects_dir = str(tmp_path / "projects")
    os.makedirs(projects_dir)
    _write_project(projects_dir, "BS-SCHED")

    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    async def _test():
        engine = Engine()
        engine.inject_ipc(MagicMock(return_value={"msg_id": "x"}), MagicMock())
        await engine._init_config_loader()
        await engine._init_state_store()
        await engine._init_fsm_engine()
        await engine._init_scheduler()
        running = engine._task_scheduler.running
        engine._task_scheduler.stop()
        return running

    assert asyncio.run(asyncio.wait_for(_test(), timeout=5)) is True


# ── Graceful shutdown：flush YAML ─────────────────────────────────────────────

def test_graceful_shutdown_flushes_yaml(tmp_path, monkeypatch):
    """graceful shutdown 将 FSM 内存状态写回 YAML。"""
    projects_dir = str(tmp_path / "projects")
    os.makedirs(projects_dir)
    yaml_path = _write_project(projects_dir, "BS-SHUT")

    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine

    async def _setup():
        engine = Engine()
        engine.inject_ipc(MagicMock(return_value={"msg_id": "x"}), MagicMock())
        await engine._init_config_loader()
        await engine._init_state_store()
        await engine._init_fsm_engine()
        await engine._init_scheduler()
        return engine

    async def _full_test():
        e = await _setup()
        model = e._fsm_engine.get_task("BS-SHUT", "T1")
        model.state = "reviewing"
        with pytest.raises(SystemExit) as exc_info:
            await e._graceful_shutdown()
        return exc_info.value.code

    code = asyncio.run(asyncio.wait_for(_full_test(), timeout=5))
    assert code == 0

    # 验证 YAML 已写入新状态
    import yaml as _yaml
    with open(yaml_path) as f:
        saved = _yaml.safe_load(f)
    tasks = saved.get("tasks", [])
    t1 = next((t for t in tasks if t.get("id") == "T1"), None)
    assert t1 is not None
    assert t1["status"] == "reviewing"


# ── 健康检查属性 ──────────────────────────────────────────────────────────────

def test_engine_health_properties(tmp_path, monkeypatch):
    """managed_projects 和 active_tasks 属性返回正确值。"""
    projects_dir = str(tmp_path / "projects")
    os.makedirs(projects_dir)
    _write_project(projects_dir, "BS-HEALTH")

    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("TMR_PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("TMR_STATE_DIR", state_dir)

    from engine import Engine
    engine = Engine()
    engine.inject_ipc(MagicMock(return_value={"msg_id": "x"}), MagicMock())

    run(engine._init_config_loader())
    run(engine._init_state_store())
    run(engine._init_fsm_engine())

    assert engine.managed_projects == 1
    assert engine.active_tasks == 1  # T1 in_progress
    assert engine.scheduler_running is False  # scheduler 未 init
