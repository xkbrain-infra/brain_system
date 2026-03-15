"""IPC Daemon Client for Service Timer - 扩展共享库.

SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
本文件仅扩展 tracked_send (IPC reliability 功能)。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import uuid
from typing import TYPE_CHECKING, Any

_spec = _ilu.spec_from_file_location(
    "ipc_daemon_client",
    "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_BaseDaemonClient = _mod.DaemonClient
IPCError = _mod.IPCError
DEFAULT_SOCKET_PATH = _mod.DEFAULT_SOCKET_PATH

if TYPE_CHECKING:
    from timer.ipc_reliability import MessageStateStore


class DaemonClient(_BaseDaemonClient):
    """DaemonClient with tracked_send for IPC reliability."""

    def tracked_send(
        self,
        from_agent: str,
        to_agent: str,
        payload: dict[str, Any],
        state_store: MessageStateStore,
        conversation_id: str | None = None,
        message_type: str = "request",
        timeout_override: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Send message with reliability tracking.

        Returns (message_id, response).
        Records message state for timeout/retry handling.
        """
        message_id = str(uuid.uuid4())

        state_store.record_send(
            message_id=message_id,
            from_agent=from_agent,
            target=to_agent,
            payload=json.dumps(payload, ensure_ascii=False),
            message_type=message_type,
            conversation_id=conversation_id,
            timeout_override=timeout_override,
        )

        try:
            resp = self.send(
                from_agent=from_agent,
                to_agent=to_agent,
                payload={**payload, "_msg_id": message_id},
                conversation_id=conversation_id,
                message_type=message_type,
            )
            return message_id, resp
        except Exception as e:
            state_store.mark_failed(message_id, f"send_error: {e}")
            raise
