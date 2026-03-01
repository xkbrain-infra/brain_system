"""
BS-025-T6 单元测试：IPC Handler
覆盖：4 种事件路由、msg_id 去重、未知类型忽略
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from ipc_handler import IPCHandler


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_msg(msg_id, event_type, project_id="BS-TEST", task_id="T1", **extra):
    content = {"event_type": event_type, "project_id": project_id, "task_id": task_id}
    content.update(extra)
    return {
        "msg_id": msg_id,
        "payload": {"content": json.dumps(content)},
    }


def _make_handler(messages, fsm_trigger=None):
    """构造 IPCHandler，ipc_recv_fn 第一次返回 messages，之后返回空。"""
    call_count = [0]

    def recv_fn(wait_seconds=30):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"messages": messages}
        return {"messages": []}

    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = False
    runtime_state.save = MagicMock()

    trigger = fsm_trigger or AsyncMock(return_value=True)

    handler = IPCHandler(
        ipc_recv_fn=recv_fn,
        fsm_trigger=trigger,
        runtime_state=runtime_state,
    )
    return handler, trigger, runtime_state


# ── TASK_PROGRESS → start ─────────────────────────────────────────────────────

def test_task_progress_routes_to_start():
    msgs = [_make_msg("m1", "TASK_PROGRESS")]
    handler, trigger, rs = _make_handler(msgs)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "start")
    rs.mark_processed.assert_called_with("m1")


# ── TASK_COMPLETED → submit ───────────────────────────────────────────────────

def test_task_completed_routes_to_submit():
    msgs = [_make_msg("m2", "TASK_COMPLETED")]
    handler, trigger, _ = _make_handler(msgs)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "submit")


# ── TASK_BLOCKED → block ──────────────────────────────────────────────────────

def test_task_blocked_routes_to_block():
    msgs = [_make_msg("m3", "TASK_BLOCKED", reason="waiting for dependency")]
    handler, trigger, _ = _make_handler(msgs)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with(
        "BS-TEST", "T1", "block", block_reason="waiting for dependency"
    )


# ── TASK_REVIEW_RESULT pass → approve ────────────────────────────────────────

def test_review_result_pass_routes_to_approve():
    msgs = [_make_msg("m4", "TASK_REVIEW_RESULT", result="pass")]
    handler, trigger, _ = _make_handler(msgs)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "approve")


# ── TASK_REVIEW_RESULT fail → request_revision ───────────────────────────────

def test_review_result_fail_routes_to_request_revision():
    msgs = [_make_msg("m5", "TASK_REVIEW_RESULT", result="fail", notes="fix test")]
    handler, trigger, _ = _make_handler(msgs)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "request_revision")


# ── 去重：重复 msg_id 幂等跳过 ───────────────────────────────────────────────

def test_duplicate_msg_id_skipped():
    msgs = [_make_msg("dup-01", "TASK_COMPLETED")]
    call_count = [0]

    def recv_fn(wait_seconds=30):
        call_count[0] += 1
        return {"messages": msgs} if call_count[0] == 1 else {"messages": []}

    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = True  # 已处理
    trigger = AsyncMock(return_value=True)

    handler = IPCHandler(
        ipc_recv_fn=recv_fn,
        fsm_trigger=trigger,
        runtime_state=runtime_state,
    )
    run(handler._recv_and_process())

    trigger.assert_not_awaited()
    runtime_state.mark_processed.assert_not_called()


# ── 未知 event_type 警告日志不抛异常 ────────────────────────────────────────

def test_unknown_event_type_ignored(caplog):
    msgs = [_make_msg("m6", "UNKNOWN_TYPE_XYZ")]
    handler, trigger, _ = _make_handler(msgs)

    import logging
    with caplog.at_level(logging.WARNING):
        run(handler._recv_and_process())

    trigger.assert_not_awaited()
    assert any("Unknown event_type" in r.message for r in caplog.records)


# ── TASK_REVIEW_RESULT unknown result 被跳过 ─────────────────────────────────

def test_review_result_unknown_value_ignored(caplog):
    msgs = [_make_msg("m7", "TASK_REVIEW_RESULT", result="maybe")]
    handler, trigger, _ = _make_handler(msgs)

    import logging
    with caplog.at_level(logging.WARNING):
        run(handler._recv_and_process())

    trigger.assert_not_awaited()


# ── ipc_recv 失败重试 ─────────────────────────────────────────────────────────

def test_recv_error_increments_error_count():
    call_count = [0]

    def failing_recv(wait_seconds=30):
        call_count[0] += 1
        raise ConnectionError("timeout")

    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = False
    trigger = AsyncMock()

    handler = IPCHandler(
        ipc_recv_fn=failing_recv,
        fsm_trigger=trigger,
        runtime_state=runtime_state,
        retry_interval=0,
    )

    run(handler._recv_and_process())

    assert handler._error_count == 1
    trigger.assert_not_awaited()


# ── 多条消息批量处理 ──────────────────────────────────────────────────────────

def test_multiple_messages_all_processed():
    msgs = [
        _make_msg("ma", "TASK_COMPLETED", task_id="T1"),
        _make_msg("mb", "TASK_PROGRESS", task_id="T2"),
    ]
    handler, trigger, rs = _make_handler(msgs)

    run(handler._recv_and_process())

    assert trigger.await_count == 2
    calls = [c.args for c in trigger.await_args_list]
    triggers_seen = {c[2] for c in calls}
    assert "submit" in triggers_seen
    assert "start" in triggers_seen


def test_start_and_stop_exits_loop():
    calls = {"n": 0}
    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = False
    trigger = AsyncMock(return_value=True)
    handler = IPCHandler(
        ipc_recv_fn=MagicMock(return_value={"messages": []}),
        fsm_trigger=trigger,
        runtime_state=runtime_state,
    )

    async def one_tick():
        calls["n"] += 1
        handler.stop()
    handler._recv_and_process = AsyncMock(side_effect=one_tick)

    run(handler.start())
    assert calls["n"] == 1


def test_recv_fn_async_coroutine_supported():
    msgs = [_make_msg("m-async", "TASK_PROGRESS")]

    async def recv_fn(wait_seconds=30):
        return {"messages": msgs}

    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = False
    trigger = AsyncMock(return_value=True)
    handler = IPCHandler(
        ipc_recv_fn=recv_fn,
        fsm_trigger=trigger,
        runtime_state=runtime_state,
    )

    run(handler._recv_and_process())
    trigger.assert_awaited_once_with("BS-TEST", "T1", "start")


def test_recv_error_stops_when_exceed_max():
    def failing_recv(wait_seconds=30):
        raise ConnectionError("timeout")

    runtime_state = MagicMock()
    runtime_state.is_processed.return_value = False
    trigger = AsyncMock()
    handler = IPCHandler(
        ipc_recv_fn=failing_recv,
        fsm_trigger=trigger,
        runtime_state=runtime_state,
        retry_interval=0,
        max_recv_errors=1,
    )
    handler._running = True

    run(handler._recv_and_process())

    assert handler._running is False
    assert handler._error_count == 1


def test_ack_called_with_msg_ids():
    msgs = [_make_msg("ack-1", "TASK_PROGRESS"), _make_msg("ack-2", "TASK_COMPLETED")]
    ack_fn = MagicMock(return_value={"ok": True})
    handler, _, _ = _make_handler(msgs)
    handler._ipc_ack_fn = ack_fn

    run(handler._recv_and_process())

    ack_fn.assert_called_once_with(msg_ids=["ack-1", "ack-2"])


def test_ack_async_and_ack_error_do_not_break():
    msgs = [_make_msg("ack-3", "TASK_PROGRESS")]

    async def bad_ack_fn(msg_ids):
        raise RuntimeError("ack failed")

    handler, trigger, _ = _make_handler(msgs)
    handler._ipc_ack_fn = bad_ack_fn

    run(handler._recv_and_process())
    trigger.assert_awaited_once()


def test_invalid_json_payload_marked_processed():
    msg = {"msg_id": "bad-json", "payload": {"content": "{not-json"}}
    handler, trigger, rs = _make_handler([msg])

    run(handler._recv_and_process())

    trigger.assert_not_awaited()
    rs.mark_processed.assert_called_with("bad-json")
    rs.save.assert_called()


def test_non_dict_payload_parse_failure_marked_processed():
    msg = {"msg_id": "bad-payload-type", "payload": object()}
    handler, trigger, rs = _make_handler([msg])

    run(handler._recv_and_process())

    trigger.assert_not_awaited()
    rs.mark_processed.assert_called_with("bad-payload-type")
    rs.save.assert_called()


def test_missing_event_type_marked_processed():
    msg = {
        "msg_id": "missing-event",
        "payload": {"content": json.dumps({"project_id": "BS-TEST", "task_id": "T1"})},
    }
    handler, trigger, rs = _make_handler([msg])

    run(handler._recv_and_process())

    trigger.assert_not_awaited()
    rs.mark_processed.assert_called_with("missing-event")
    rs.save.assert_called()


def test_missing_project_or_task_skips_dispatch_but_marks_processed():
    msg = _make_msg("missing-task", "TASK_PROGRESS", task_id="")
    handler, trigger, rs = _make_handler([msg])

    run(handler._recv_and_process())

    trigger.assert_not_awaited()
    rs.mark_processed.assert_called_with("missing-task")
    rs.save.assert_called()


def test_fsm_trigger_returns_false_is_tolerated():
    msg = _make_msg("fsm-false", "TASK_PROGRESS")
    trigger = AsyncMock(return_value=False)
    handler, _, rs = _make_handler([msg], fsm_trigger=trigger)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "start")
    rs.mark_processed.assert_called_with("fsm-false")


def test_fsm_trigger_exception_is_tolerated_and_marked_processed():
    msg = _make_msg("fsm-ex", "TASK_PROGRESS")
    trigger = AsyncMock(side_effect=RuntimeError("boom"))
    handler, _, rs = _make_handler([msg], fsm_trigger=trigger)

    run(handler._recv_and_process())

    trigger.assert_awaited_once_with("BS-TEST", "T1", "start")
    rs.mark_processed.assert_called_with("fsm-ex")
