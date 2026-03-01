"""IPC Daemon Client - 共享库 (SSOT)

brain_ipc Unix Socket 通信的统一客户端。
所有需要与 brain_ipc 通信的服务必须导入此模块，禁止自行实现。

使用方式:
    # 方式 1: 直接添加 utils 到 sys.path
    import sys; sys.path.insert(0, "/brain/infrastructure/service/utils/ipc/bin/current")
    from daemon_client import DaemonClient

    # 方式 2: 包导入 (如果 infrastructure 在 sys.path 中)
    from infrastructure.service.utils.ipc import DaemonClient

    client = DaemonClient()
    client.send(from_agent="timer", to_agent="pmo", payload={...})

消费者:
    - gateway/webhook_gateway.py
    - timer/service_timer.py (+ tracked_send 扩展)
    - service-agentctl/core/dispatcher.py (BrainDaemonClient alias)
    - dashboard/core/collector.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any, AsyncIterator

DEFAULT_SOCKET_PATH = "/tmp/brain_ipc.sock"
DEFAULT_NOTIFY_SOCKET_PATH = "/tmp/brain_ipc_notify.sock"

logger = logging.getLogger("ipc")


class IPCError(RuntimeError):
    """IPC communication error."""
    pass


class DaemonClient:
    """Client for communicating with brain_ipc via Unix Socket."""

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH) -> None:
        self.socket_path = socket_path

    def _send_request(
        self,
        action: str,
        data: dict[str, Any],
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        """Send request to daemon and get response."""
        request = {"action": action, "data": data}
        request_json = json.dumps(request, ensure_ascii=False) + "\n"

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout_s)
            sock.connect(self.socket_path)
            sock.sendall(request_json.encode("utf-8"))

            data_bytes = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data_bytes += chunk
                if b"\n" in data_bytes:
                    break

            sock.close()

            if not data_bytes:
                raise IPCError("Empty response from daemon")

            return json.loads(data_bytes.decode("utf-8"))

        except FileNotFoundError as e:
            raise IPCError(f"Daemon socket not found: {self.socket_path}") from e
        except ConnectionRefusedError as e:
            raise IPCError(f"Daemon not running at: {self.socket_path}") from e
        except socket.timeout as e:
            raise IPCError("Daemon request timeout") from e
        except json.JSONDecodeError as e:
            raise IPCError(f"Invalid daemon response: {e}") from e

    def register(
        self,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
        instance_id: str | None = None,
        tmux_session: str = "",
        tmux_pane: str = "",
    ) -> dict[str, Any]:
        """Register as an agent."""
        data: dict[str, Any] = {
            "agent_name": agent_name,
            "metadata": metadata or {},
        }
        if instance_id:
            data["instance_id"] = instance_id
        if tmux_session:
            data["tmux_session"] = tmux_session
        if tmux_pane:
            data["tmux_pane"] = tmux_pane
        return self._send_request("agent_register", data)

    def register_service(
        self,
        service_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register as a service (no tmux required)."""
        return self._send_request("service_register", {
            "service_name": service_name,
            "metadata": metadata or {},
        })

    def service_heartbeat(self, service_name: str) -> dict[str, Any]:
        """Send heartbeat for a service."""
        return self._send_request("service_heartbeat", {
            "service_name": service_name,
        })

    def send(
        self,
        from_agent: str,
        to_agent: str,
        payload: dict[str, Any],
        conversation_id: str | None = None,
        message_type: str = "request",
    ) -> dict[str, Any]:
        """Send a message to another agent."""
        return self._send_request("ipc_send", {
            "from": from_agent,
            "to": to_agent,
            "payload": payload,
            "conversation_id": conversation_id,
            "message_type": message_type,
        })

    def recv(
        self,
        agent_name: str,
        ack_mode: str = "auto",
        conversation_id: str | None = None,
        max_items: int = 10,
    ) -> dict[str, Any]:
        """Receive messages for an agent."""
        return self._send_request("ipc_recv", {
            "agent": agent_name,
            "ack_mode": ack_mode,
            "conversation_id": conversation_id,
            "max_items": max_items,
        })

    def ack(self, agent_name: str, msg_ids: list[str]) -> dict[str, Any]:
        """Acknowledge messages."""
        return self._send_request("ipc_ack", {
            "agent": agent_name,
            "msg_ids": msg_ids,
        })

    def list_agents(self, include_offline: bool = False) -> dict[str, Any]:
        """List registered agents."""
        return self._send_request("agent_list", {
            "include_offline": include_offline,
        })

    def ping(self) -> bool:
        """Check if daemon is alive."""
        try:
            response = self._send_request("ping", {})
            return response.get("status") in ("ok", "pong")
        except Exception:
            return False


class NotifyClient:
    """Push-based IPC listener via daemon notify socket.

    Connects to ipc_notify.sock and yields notifications when messages
    arrive for the specified service. Replaces busy-polling with blocking I/O.

    Usage:
        notify = NotifyClient("service-agentctl")
        async for event in notify.listen():
            # event = {"event":"ipc_message","msg_id":"...","to":"...","from":"..."}
            messages = daemon.recv("service-agentctl", ack_mode="manual")
            ...
    """

    def __init__(
        self,
        service_name: str,
        notify_socket_path: str = DEFAULT_NOTIFY_SOCKET_PATH,
        reconnect_delay: float = 2.0,
    ) -> None:
        self.service_name = service_name
        self.notify_socket_path = notify_socket_path
        self.reconnect_delay = reconnect_delay

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Yield notification events addressed to this service. Auto-reconnects."""
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(self.notify_socket_path)
                logger.info("NotifyClient(%s): connected to %s", self.service_name, self.notify_socket_path)
                try:
                    while True:
                        line = await reader.readline()
                        if not line:
                            break  # server closed
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        to = event.get("to", "")
                        to_raw = event.get("to_raw", "")
                        if self.service_name in (to, to_raw):
                            yield event
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
            except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
                logger.warning("NotifyClient(%s): connect failed (%s), retry in %.1fs",
                               self.service_name, e, self.reconnect_delay)
            await asyncio.sleep(self.reconnect_delay)


# Alias for backward compatibility with agentctl
BrainDaemonClient = DaemonClient
