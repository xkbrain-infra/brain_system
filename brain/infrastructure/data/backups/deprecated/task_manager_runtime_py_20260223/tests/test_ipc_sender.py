"""
BS-025-T4 单元测试：IPC Sender
覆盖：首次成功、重试成功、3 次失败后 ERROR 日志
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from ipc_sender import BACKOFF_SECONDS, MAX_RETRIES, IPCSender


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── 首次成功 ──────────────────────────────────────────────────────────────────

def test_send_message_first_attempt_success():
    """首次发送成功，无重试，返回 True。"""
    mock_fn = MagicMock(return_value={"msg_id": "abc123"})
    sender = IPCSender("task_manager_runtime", mock_fn)

    result = run(sender.send_message("agent_qa", "TASK_REVIEW_READY", {"task_id": "T1"}))

    assert result is True
    assert mock_fn.call_count == 1


# ── 重试成功 ──────────────────────────────────────────────────────────────────

def test_send_message_retry_success():
    """首次失败、第二次成功：1 次重试，返回 True。"""
    call_count = 0

    def flaky_send(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("timeout")
        return {"msg_id": "retry-ok"}

    sender = IPCSender("task_manager_runtime", flaky_send)

    with patch("ipc_sender.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = run(sender.send_message("agent_orch", "TASK_OVERDUE", {"task_id": "T2"}))

    assert result is True
    assert call_count == 2
    mock_sleep.assert_awaited_once_with(BACKOFF_SECONDS[0])


def test_send_message_retries_with_exponential_backoff():
    """前两次失败、第三次成功，确认 backoff 间隔正确（1s, 2s）。"""
    call_count = 0

    def flaky(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("err")
        return {"msg_id": "ok"}

    sender = IPCSender("tmr", flaky)

    with patch("ipc_sender.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = run(sender.send_message("to", "TASK_ASSIGNED", {}))

    assert result is True
    assert call_count == 3
    assert mock_sleep.await_args_list == [call(1), call(2)]


# ── 3 次全失败 ────────────────────────────────────────────────────────────────

def test_send_message_all_retries_fail(caplog):
    """连续 3 次失败：返回 False，记录 ERROR 日志。"""
    mock_fn = MagicMock(side_effect=RuntimeError("always fails"))
    sender = IPCSender("tmr", mock_fn)

    with patch("ipc_sender.asyncio.sleep", new_callable=AsyncMock):
        with caplog.at_level("ERROR"):
            result = run(sender.send_message("agent_x", "TASK_BLOCKED", {"task_id": "T3"}))

    assert result is False
    assert mock_fn.call_count == MAX_RETRIES
    assert any("FAILED" in r.message for r in caplog.records)


def test_send_message_no_exception_on_total_failure():
    """3 次失败不抛出异常（调用方仅得到 False）。"""
    mock_fn = MagicMock(side_effect=Exception("boom"))
    sender = IPCSender("tmr", mock_fn)

    with patch("ipc_sender.asyncio.sleep", new_callable=AsyncMock):
        result = run(sender.send_message("to", "TASK_OVERDUE", {}))

    assert result is False  # 不抛出异常


# ── 便捷方法 ──────────────────────────────────────────────────────────────────

def test_send_task_assigned_payload():
    """send_task_assigned 发送包含正确字段的消息。"""
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return {"msg_id": "x"}

    sender = IPCSender("tmr", capture)
    run(sender.send_task_assigned(
        to="agent_dev",
        project_id="BS-025",
        task_id="BS-025-T5",
        task_title="FSM 引擎",
        task_description="实现 AsyncMachine",
        assigned_agent="agent_bs025_dev",
        priority="high",
    ))

    import json
    msg = captured["message"]
    assert "TASK_ASSIGNED" in msg
    body = json.loads(msg.split("\n", 1)[1])
    assert body["project_id"] == "BS-025"
    assert body["task_id"] == "BS-025-T5"
    assert body["assigned_agent"] == "agent_bs025_dev"
    assert body["priority"] == "high"


def test_send_task_overdue_payload():
    """send_task_overdue 包含 overdue_minutes 和 overdue_count 字段。"""
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return {"msg_id": "y"}

    sender = IPCSender("tmr", capture)
    run(sender.send_task_overdue(
        to="agent_orch",
        project_id="BS-025",
        task_id="BS-025-T1",
        assigned_agent="agent_dev",
        overdue_minutes=45,
        overdue_count=2,
    ))

    import json
    body = json.loads(captured["message"].split("\n", 1)[1])
    assert body["overdue_minutes"] == 45
    assert body["overdue_count"] == 2


def test_send_task_available_payload():
    """send_task_available 包含 pending_count 和 available_agents。"""
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return {"msg_id": "z"}

    sender = IPCSender("tmr", capture)
    run(sender.send_task_available(
        to="agent_orch",
        project_id="BS-025",
        pending_count=3,
        available_agents=["agent_dev", "agent_dev2"],
    ))

    import json
    body = json.loads(captured["message"].split("\n", 1)[1])
    assert body["pending_count"] == 3
    assert body["available_agents"] == ["agent_dev", "agent_dev2"]
