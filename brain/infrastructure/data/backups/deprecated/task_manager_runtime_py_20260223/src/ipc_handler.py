"""
BS-025-MOD-ipc-handler: IPC Handler
asyncio 长轮询 IPC 消息，去重，路由到 FSM trigger。
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# 支持的 inbound 事件类型 → FSM trigger 映射
_EVENT_TO_TRIGGER: Dict[str, str] = {
    "TASK_PROGRESS":       "start",            # 首次收到进度 → start_task
    "TASK_COMPLETED":      "submit",            # agent 完成 → submit（进入 reviewing）
    "TASK_BLOCKED":        "block",             # agent 报告阻塞 → block_task
}

# TASK_REVIEW_RESULT 需要根据 result 字段分发，单独处理
_REVIEW_RESULT_PASS_TRIGGER = "approve"
_REVIEW_RESULT_FAIL_TRIGGER = "request_revision"


class IPCHandler:
    """
    持续从 IPC 消息队列接收消息，去重后路由到 FSMEngine。
    通过 runtime_state 持久化 processed_msg_ids 实现重启后幂等去重。

    ipc_recv_fn: 可调用，接受 wait_seconds 参数，返回消息列表
    ipc_ack_fn:  可调用（可选），接受 msg_ids 列表
    fsm_trigger: 可调用，签名 async (project_id, task_id, trigger, **kwargs) -> bool
    runtime_state: RuntimeState 实例（提供 is_processed / mark_processed / save）
    """

    def __init__(
        self,
        ipc_recv_fn: Callable,
        fsm_trigger: Callable,
        runtime_state,
        ipc_ack_fn: Optional[Callable] = None,
        wait_seconds: int = 30,
        retry_interval: int = 5,
        max_recv_errors: int = 10,
    ):
        self._ipc_recv_fn = ipc_recv_fn
        self._ipc_ack_fn = ipc_ack_fn
        self._fsm_trigger = fsm_trigger
        self._runtime_state = runtime_state
        self._wait_seconds = wait_seconds
        self._retry_interval = retry_interval
        self._max_recv_errors = max_recv_errors

        self._running = False
        self._error_count = 0

    async def start(self) -> None:
        """启动消息接收循环（阻塞，直到 stop() 被调用）。"""
        self._running = True
        logger.info("IPCHandler started")
        while self._running:
            await self._recv_and_process()

    def stop(self) -> None:
        self._running = False

    async def _recv_and_process(self) -> None:
        """单次 ipc_recv 调用 + 消息处理。"""
        try:
            result = self._ipc_recv_fn(wait_seconds=self._wait_seconds)
            if asyncio.iscoroutine(result):
                result = await result
            self._error_count = 0
        except Exception as e:
            self._error_count += 1
            logger.warning(
                f"ipc_recv failed ({self._error_count}/{self._max_recv_errors}): {e}"
            )
            if self._error_count >= self._max_recv_errors:
                logger.critical("ipc_recv consecutive failures exceeded limit, stopping")
                self._running = False
                return
            await asyncio.sleep(self._retry_interval)
            return

        messages = result.get("messages", []) if isinstance(result, dict) else []
        if not messages:
            return

        msg_ids_to_ack = []
        for msg in messages:
            msg_id = msg.get("msg_id", "")
            msg_ids_to_ack.append(msg_id)
            await self._handle_message(msg)

        # ACK（若 ipc_ack_fn 已提供）
        if self._ipc_ack_fn and msg_ids_to_ack:
            try:
                ack_result = self._ipc_ack_fn(msg_ids=msg_ids_to_ack)
                if asyncio.iscoroutine(ack_result):
                    await ack_result
            except Exception as e:
                logger.warning(f"ipc_ack failed: {e}")

    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        """处理单条消息：去重 → 解析 → 路由。"""
        msg_id = msg.get("msg_id", "")

        # 幂等去重
        if self._runtime_state.is_processed(msg_id):
            logger.debug(f"Duplicate msg_id={msg_id}, skipping")
            return

        # 解析 payload
        payload = msg.get("payload", {})
        if isinstance(payload, dict):
            content_raw = payload.get("content", "{}")
        else:
            content_raw = str(payload)

        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Cannot parse message content, msg_id={msg_id}, skipping")
            self._runtime_state.mark_processed(msg_id)
            self._runtime_state.save()
            return

        event_type = content.get("event_type", "")
        project_id = content.get("project_id", "")
        task_id = content.get("task_id", "")

        if not event_type:
            logger.warning(f"Missing event_type in msg_id={msg_id}, skipping")
            self._runtime_state.mark_processed(msg_id)
            self._runtime_state.save()
            return

        # 路由
        await self._route(event_type, project_id, task_id, content, msg_id)

        # 标记已处理并持久化
        self._runtime_state.mark_processed(msg_id)
        self._runtime_state.save()

    async def _route(
        self,
        event_type: str,
        project_id: str,
        task_id: str,
        content: Dict[str, Any],
        msg_id: str,
    ) -> None:
        """根据 event_type 路由到对应 FSM trigger。"""

        if event_type == "TASK_REVIEW_RESULT":
            result_val = content.get("result", "")
            if result_val == "pass":
                trigger = _REVIEW_RESULT_PASS_TRIGGER
            elif result_val == "fail":
                trigger = _REVIEW_RESULT_FAIL_TRIGGER
            else:
                logger.warning(
                    f"TASK_REVIEW_RESULT unknown result='{result_val}' "
                    f"msg_id={msg_id}, skipping"
                )
                return

            await self._dispatch(project_id, task_id, trigger, msg_id)
            return

        trigger = _EVENT_TO_TRIGGER.get(event_type)
        if trigger is None:
            logger.warning(
                f"Unknown event_type='{event_type}' msg_id={msg_id}, ignoring"
            )
            return

        # 附加字段注入（如 block_reason）
        kwargs: Dict[str, Any] = {}
        if event_type == "TASK_BLOCKED":
            kwargs["block_reason"] = content.get("reason", "")

        await self._dispatch(project_id, task_id, trigger, msg_id, **kwargs)

    async def _dispatch(
        self,
        project_id: str,
        task_id: str,
        trigger: str,
        msg_id: str,
        **kwargs: Any,
    ) -> None:
        """调用 FSM trigger，处理结果日志。"""
        if not project_id or not task_id:
            logger.warning(
                f"Missing project_id/task_id for trigger={trigger} msg_id={msg_id}"
            )
            return
        try:
            ok = await self._fsm_trigger(project_id, task_id, trigger, **kwargs)
            if ok:
                logger.info(
                    f"FSM trigger '{trigger}' OK: {project_id}/{task_id} msg_id={msg_id}"
                )
            else:
                logger.warning(
                    f"FSM trigger '{trigger}' rejected: {project_id}/{task_id} "
                    f"(invalid transition or task not found) msg_id={msg_id}"
                )
        except Exception as e:
            logger.error(
                f"FSM trigger '{trigger}' exception: {project_id}/{task_id} "
                f"msg_id={msg_id} error={e}"
            )
