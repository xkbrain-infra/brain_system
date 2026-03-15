"""
BS-025-T7 单元测试：Scheduler
覆盖：未超时无事件、超时一次发 TASK_OVERDUE、连续超时触发 block
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from scheduler import TaskScanContext


def run(coro):
    return asyncio.run(coro)


def _make_task(task_id, status="in_progress", start_time=None, overdue_count=0):
    return {
        "id": task_id,
        "status": status,
        "start_time": start_time,
        "overdue_count": overdue_count,
        "assigned_to": "agent_dev",
    }


def _past(seconds: int) -> str:
    """返回 `seconds` 秒前的 ISO8601 时间戳。"""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _make_ctx(tasks, timeout_duration=3600, escalation_threshold=2,
              ipc_sender=None, fsm_trigger=None):
    updated_overdue = {}

    def get_tasks():
        return tasks

    def update_overdue(project_id, task_id, count):
        updated_overdue[(project_id, task_id)] = count

    ctx = TaskScanContext(
        project_id="BS-TEST",
        timeout_duration=timeout_duration,
        escalation_threshold=escalation_threshold,
        orchestrator_agent="agent_orch",
        ipc_sender=ipc_sender or AsyncMock(),
        fsm_trigger=fsm_trigger or AsyncMock(return_value=True),
        state_store_get_tasks=get_tasks,
        state_store_update_overdue=update_overdue,
    )
    return ctx, updated_overdue


# ── 未超时：无任何事件 ────────────────────────────────────────────────────────

def test_no_overdue_when_within_timeout():
    """任务在超时时间内，不发 TASK_OVERDUE，不触发 block。"""
    tasks = [_make_task("T1", start_time=_past(100))]
    mock_sender = AsyncMock()
    mock_trigger = AsyncMock(return_value=True)
    ctx, _ = _make_ctx(
        tasks, timeout_duration=3600,
        ipc_sender=mock_sender, fsm_trigger=mock_trigger
    )

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_not_awaited()
    mock_trigger.assert_not_awaited()


def test_no_overdue_for_done_task():
    """已完成任务不参与超时检测。"""
    tasks = [_make_task("T1", status="done", start_time=_past(99999))]
    mock_sender = AsyncMock()
    ctx, _ = _make_ctx(tasks, ipc_sender=mock_sender)

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_not_awaited()


def test_no_overdue_for_task_without_start_time():
    """没有 start_time 的任务跳过检测。"""
    tasks = [_make_task("T1", start_time=None)]
    mock_sender = AsyncMock()
    ctx, _ = _make_ctx(tasks, ipc_sender=mock_sender)

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_not_awaited()


# ── 超时一次：发 TASK_OVERDUE，不 block ──────────────────────────────────────

def test_first_overdue_sends_task_overdue():
    """任务超时一次，发送 TASK_OVERDUE，overdue_count 更新为 1，不触发 block。"""
    tasks = [_make_task("T1", start_time=_past(7200), overdue_count=0)]
    mock_sender = AsyncMock()
    mock_trigger = AsyncMock(return_value=True)
    ctx, updated = _make_ctx(
        tasks, timeout_duration=3600, escalation_threshold=2,
        ipc_sender=mock_sender, fsm_trigger=mock_trigger
    )

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_awaited_once()
    call_kwargs = mock_sender.send_task_overdue.await_args.kwargs
    assert call_kwargs["project_id"] == "BS-TEST"
    assert call_kwargs["task_id"] == "T1"
    assert call_kwargs["overdue_count"] == 1
    assert call_kwargs["overdue_minutes"] >= 120

    # 未达阈值（1 < 2），不触发 block
    mock_trigger.assert_not_awaited()
    assert updated[("BS-TEST", "T1")] == 1


# ── 连续超时达阈值：触发 FSM block ───────────────────────────────────────────

def test_escalation_triggers_block():
    """overdue_count 达到 escalation_threshold 时触发 FSM block。"""
    # 任务已经超时 1 次（overdue_count=1），本次再超时 → overdue_count=2 = threshold
    tasks = [_make_task("T1", start_time=_past(7200), overdue_count=1)]
    mock_sender = AsyncMock()
    mock_trigger = AsyncMock(return_value=True)
    ctx, updated = _make_ctx(
        tasks, timeout_duration=3600, escalation_threshold=2,
        ipc_sender=mock_sender, fsm_trigger=mock_trigger
    )

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_awaited_once()
    mock_trigger.assert_awaited_once()

    trigger_call = mock_trigger.await_args
    assert trigger_call.args == ("BS-TEST", "T1", "block")
    assert "block_reason" in trigger_call.kwargs
    assert updated[("BS-TEST", "T1")] == 2


def test_escalation_threshold_3_not_triggered_at_2():
    """阈值为 3 时，overdue_count=2 不触发 block。"""
    tasks = [_make_task("T1", start_time=_past(7200), overdue_count=1)]
    mock_trigger = AsyncMock(return_value=True)
    ctx, _ = _make_ctx(
        tasks, timeout_duration=3600, escalation_threshold=3,
        fsm_trigger=mock_trigger
    )

    run(ctx.scan())

    mock_trigger.assert_not_awaited()


# ── 多任务独立检测 ────────────────────────────────────────────────────────────

def test_multiple_tasks_independent():
    """多个任务独立检测：超时的发通知，未超时的不发。"""
    tasks = [
        _make_task("T1", start_time=_past(7200)),  # 超时
        _make_task("T2", start_time=_past(100)),   # 未超时
        _make_task("T3", status="done", start_time=_past(9999)),  # done，跳过
    ]
    mock_sender = AsyncMock()
    mock_trigger = AsyncMock(return_value=True)
    ctx, updated = _make_ctx(
        tasks, timeout_duration=3600, escalation_threshold=5,
        ipc_sender=mock_sender, fsm_trigger=mock_trigger
    )

    run(ctx.scan())

    # 只有 T1 超时
    assert mock_sender.send_task_overdue.await_count == 1
    call_kwargs = mock_sender.send_task_overdue.await_args.kwargs
    assert call_kwargs["task_id"] == "T1"

    assert ("BS-TEST", "T1") in updated
    assert ("BS-TEST", "T2") not in updated
    assert ("BS-TEST", "T3") not in updated


# ── assigned 状态也参与超时检测 ──────────────────────────────────────────────

def test_assigned_status_also_checked():
    """assigned 状态的任务也参与超时检测。"""
    tasks = [_make_task("T1", status="assigned", start_time=_past(7200))]
    mock_sender = AsyncMock()
    ctx, updated = _make_ctx(tasks, timeout_duration=3600, ipc_sender=mock_sender)

    run(ctx.scan())

    mock_sender.send_task_overdue.assert_awaited_once()
