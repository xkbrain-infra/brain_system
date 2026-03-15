"""
BS-025-T5 单元测试：FSM Engine
覆盖：全路径转换、revision 分支、blocked 分支、非法转换拒绝、事件序列化
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from fsm import FSMEngine, TaskModel, STATES


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_engine():
    return FSMEngine()


def make_model(engine, project_id="BS-TEST", task_id="T1",
               initial_state="pending", ipc_sender=None, state_store=None):
    return engine.create_task(
        project_id=project_id,
        task_id=task_id,
        ipc_sender=ipc_sender,
        state_store=state_store,
        orchestrator_agent="agent_orch",
        qa_agent="agent_qa",
        yaml_path="/fake/path.yaml",
        initial_state=initial_state,
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── 全路径转换：pending → done ────────────────────────────────────────────────

def test_full_happy_path():
    """pending → assigned → in_progress → reviewing → done 完整路径。"""
    engine = make_engine()
    model = make_model(engine)

    assert model.state == "pending"

    run(model.assign())
    assert model.state == "assigned"

    run(model.start())
    assert model.state == "in_progress"

    run(model.submit())
    assert model.state == "reviewing"

    run(model.approve())
    assert model.state == "done"


# ── revision 分支 ─────────────────────────────────────────────────────────────

def test_revision_branch():
    """reviewing → revision → in_progress → reviewing → done。"""
    engine = make_engine()
    model = make_model(engine, initial_state="reviewing")

    run(model.request_revision())
    assert model.state == "revision"

    run(model.resubmit())
    assert model.state == "in_progress"

    run(model.submit())
    assert model.state == "reviewing"

    run(model.approve())
    assert model.state == "done"


# ── blocked 分支 ──────────────────────────────────────────────────────────────

def test_blocked_from_in_progress():
    """in_progress → blocked → in_progress（unblock 后重置 overdue_count）。"""
    engine = make_engine()
    model = make_model(engine, initial_state="in_progress")

    run(model.block())
    assert model.state == "blocked"

    run(model.unblock())
    assert model.state == "in_progress"
    assert model.overdue_count == 0


def test_blocked_from_assigned():
    """assigned → blocked → in_progress。"""
    engine = make_engine()
    model = make_model(engine, initial_state="assigned")

    run(model.block())
    assert model.state == "blocked"

    run(model.unblock())
    assert model.state == "in_progress"


# ── fail / retry ──────────────────────────────────────────────────────────────

def test_fail_and_retry():
    """in_progress → failed → pending（retry）。"""
    engine = make_engine()
    model = make_model(engine, initial_state="in_progress")

    run(model.fail())
    assert model.state == "failed"

    run(model.retry())
    assert model.state == "pending"


def test_fail_from_blocked():
    """blocked → failed。"""
    engine = make_engine()
    model = make_model(engine, initial_state="blocked")

    run(model.fail())
    assert model.state == "failed"


# ── cancel ────────────────────────────────────────────────────────────────────

def test_cancel_from_various_states():
    """pending/assigned/in_progress/blocked/revision 均可 cancel。"""
    cancellable = ["pending", "assigned", "in_progress", "blocked", "revision"]
    for state in cancellable:
        engine = make_engine()
        model = make_model(engine, initial_state=state)
        run(model.cancel())
        assert model.state == "cancelled", f"cancel from {state} failed"


# ── 非法转换被拒绝 ────────────────────────────────────────────────────────────

def test_invalid_transition_raises():
    """非法转换应被拒绝（MachineError），不修改状态。"""
    from transitions import MachineError
    engine = make_engine()
    model = make_model(engine, initial_state="done")

    with pytest.raises(MachineError):
        run(model.assign())   # done 不能再 assign

    assert model.state == "done"


def test_invalid_transition_via_engine_returns_false():
    """通过 FSMEngine.trigger 触发非法转换返回 False，不抛异常。"""
    engine = make_engine()
    make_model(engine, initial_state="done")

    result = run(engine.trigger("BS-TEST", "T1", "assign"))
    assert result is False


def test_unknown_task_trigger_returns_false():
    """对不存在的 task 触发 trigger 返回 False。"""
    engine = make_engine()
    result = run(engine.trigger("NO-PROJ", "NO-TASK", "assign"))
    assert result is False


# ── 事件序列化（queued='model'）────────────────────────────────────────────────

def test_queued_serializes_concurrent_events():
    """
    并发触发多个 trigger 时，queued='model' 保证顺序执行，不产生竞态。
    """
    engine = make_engine()
    model = make_model(engine, initial_state="pending")

    async def concurrent():
        await asyncio.gather(
            model.assign(),
            model.assign(),  # 第二个会因非法转换被拒绝
        )

    # 不应抛出未捕获异常
    try:
        run(concurrent())
    except Exception:
        pass  # 第二个 assign 抛 MachineError 是预期行为

    # 最终状态确定（assigned），无中间损坏状态
    assert model.state == "assigned"


# ── IPC 回调触发 ──────────────────────────────────────────────────────────────

def test_on_enter_reviewing_sends_review_ready():
    """进入 reviewing 状态时，IPCSender.send_task_review_ready 被调用。"""
    mock_sender = AsyncMock()
    engine = make_engine()
    model = make_model(engine, initial_state="in_progress", ipc_sender=mock_sender)
    model.assigned_to = "agent_dev"

    run(model.submit())

    mock_sender.send_task_review_ready.assert_awaited_once()
    call_kwargs = mock_sender.send_task_review_ready.await_args
    assert call_kwargs.kwargs.get("to") == "agent_qa" or \
           call_kwargs.args[0] == "agent_qa"


def test_on_enter_blocked_sends_task_blocked():
    """进入 blocked 状态时，IPCSender.send_message 以 TASK_BLOCKED 被调用。"""
    mock_sender = AsyncMock()
    engine = make_engine()
    model = make_model(engine, initial_state="in_progress", ipc_sender=mock_sender)
    model.block_reason = "waiting for external API"

    run(model.block())

    mock_sender.send_message.assert_awaited_once()
    args = mock_sender.send_message.await_args
    assert args.kwargs.get("event_type") == "TASK_BLOCKED" or \
           args.args[1] == "TASK_BLOCKED"


def test_on_enter_assigned_sends_task_assigned():
    """进入 assigned 状态时，IPCSender.send_task_assigned 被调用（assigned_to 已设置）。"""
    mock_sender = AsyncMock()
    engine = make_engine()
    model = make_model(engine, initial_state="pending", ipc_sender=mock_sender)
    model.assigned_to = "agent_dev"

    run(model.assign())

    mock_sender.send_task_assigned.assert_awaited_once()


# ── start_time 记录 ───────────────────────────────────────────────────────────

def test_start_time_set_on_enter_in_progress():
    """首次进入 in_progress 时 start_time 被设置，再次进入不覆盖。"""
    engine = make_engine()
    model = make_model(engine, initial_state="assigned")

    assert model.start_time is None
    run(model.start())
    first_time = model.start_time
    assert first_time is not None

    # 模拟 blocked → unblock → in_progress，start_time 不应被重置
    run(model.block())
    run(model.unblock())
    assert model.start_time == first_time


# ── FSMEngine CRUD ────────────────────────────────────────────────────────────

def test_get_or_create_returns_existing():
    """get_or_create 对已存在的 task 返回同一实例。"""
    engine = make_engine()
    m1 = make_model(engine, task_id="T1")
    m2 = engine.get_or_create(
        "BS-TEST", "T1", None, None, "agent_orch", "agent_qa", "/fake"
    )
    assert m1 is m2


def test_remove_task():
    """remove_task 后 get_task 返回 None。"""
    engine = make_engine()
    make_model(engine, task_id="T-RM")
    engine.remove_task("BS-TEST", "T-RM")
    assert engine.get_task("BS-TEST", "T-RM") is None
