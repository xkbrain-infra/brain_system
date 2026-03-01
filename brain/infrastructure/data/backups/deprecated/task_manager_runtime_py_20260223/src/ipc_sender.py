"""
BS-025-MOD-ipc-sender: IPC Sender
带重试的 IPC 消息发送封装（最多 3 次，指数退避 1s/2s/4s）
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]

SUPPORTED_EVENT_TYPES = {
    "TASK_ASSIGNED",
    "TASK_OVERDUE",
    "TASK_REVIEW_READY",
    "TASK_AVAILABLE",
    "TASK_BLOCKED",
}


class IPCSender:
    """
    封装 ipc_send MCP 工具调用，提供：
    - 自动重试（最多 3 次，指数退避 1s/2s/4s）
    - 标准化消息格式（含 event_type、project_id、task_id）
    - 每条消息审计日志（to、event_type、msg_id）
    """

    def __init__(self, agent_name: str, ipc_send_fn: Callable):
        """
        agent_name: 发送方标识（用于日志）
        ipc_send_fn: 实际调用 ipc_send 的可调用对象（支持 async 和 sync）
        """
        self.agent_name = agent_name
        self._ipc_send_fn = ipc_send_fn

    async def send_message(
        self,
        to: str,
        event_type: str,
        payload: Dict[str, Any],
        conversation_id: Optional[str] = None,
    ) -> bool:
        """
        发送 IPC 消息，最多重试 3 次（指数退避 1s/2s/4s）。
        返回 True 表示发送成功，False 表示所有重试均失败。
        每次尝试均记录日志（含 to、event_type、msg_id）。
        """
        body = json.dumps({"event_type": event_type, **payload}, ensure_ascii=False)
        message = f"[task_manager_runtime] {event_type}\n{body}"

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                kwargs: Dict[str, Any] = {"to": to, "message": message}
                if conversation_id:
                    kwargs["conversation_id"] = conversation_id

                result = self._ipc_send_fn(**kwargs)
                if asyncio.iscoroutine(result):
                    result = await result

                msg_id = (
                    result.get("msg_id", "unknown")
                    if isinstance(result, dict)
                    else "unknown"
                )
                logger.info(
                    f"IPC sent: to={to} event_type={event_type} "
                    f"msg_id={msg_id} attempt={attempt + 1}"
                )
                return True

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = BACKOFF_SECONDS[attempt]
                    logger.warning(
                        f"IPC send failed (attempt {attempt + 1}/{MAX_RETRIES}): "
                        f"to={to} event_type={event_type} error={e}, "
                        f"retrying in {wait}s"
                    )
                    await asyncio.sleep(wait)

        logger.error(
            f"IPC send FAILED after {MAX_RETRIES} attempts: "
            f"to={to} event_type={event_type} last_error={last_error}"
        )
        return False

    # ── 便捷方法 ─────────────────────────────────────────────────────────────

    async def send_task_assigned(
        self,
        to: str,
        project_id: str,
        task_id: str,
        task_title: str,
        task_description: str,
        assigned_agent: str,
        priority: str = "medium",
        conversation_id: Optional[str] = None,
    ) -> bool:
        return await self.send_message(
            to, "TASK_ASSIGNED",
            {
                "project_id": project_id,
                "task_id": task_id,
                "task_title": task_title,
                "task_description": task_description,
                "assigned_agent": assigned_agent,
                "priority": priority,
            },
            conversation_id,
        )

    async def send_task_overdue(
        self,
        to: str,
        project_id: str,
        task_id: str,
        assigned_agent: str,
        overdue_minutes: int,
        overdue_count: int,
        conversation_id: Optional[str] = None,
    ) -> bool:
        return await self.send_message(
            to, "TASK_OVERDUE",
            {
                "project_id": project_id,
                "task_id": task_id,
                "assigned_agent": assigned_agent,
                "overdue_minutes": overdue_minutes,
                "overdue_count": overdue_count,
            },
            conversation_id,
        )

    async def send_task_review_ready(
        self,
        to: str,
        project_id: str,
        task_id: str,
        submitted_by: str,
        conversation_id: Optional[str] = None,
    ) -> bool:
        return await self.send_message(
            to, "TASK_REVIEW_READY",
            {
                "project_id": project_id,
                "task_id": task_id,
                "submitted_by": submitted_by,
            },
            conversation_id,
        )

    async def send_task_available(
        self,
        to: str,
        project_id: str,
        pending_count: int,
        available_agents: List[str],
        conversation_id: Optional[str] = None,
    ) -> bool:
        return await self.send_message(
            to, "TASK_AVAILABLE",
            {
                "project_id": project_id,
                "pending_count": pending_count,
                "available_agents": available_agents,
            },
            conversation_id,
        )
