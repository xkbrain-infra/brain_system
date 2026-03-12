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

import json
import hmac
import hashlib
import secrets
import time
import socket
from typing import Any

DEFAULT_SOCKET_PATH = "/tmp/brain_ipc.sock"
SECRET_KEY_PATH = "/xkagent_infra/brain/infrastructure/service/brain_ipc/config/secret.key"


def _load_secret_key() -> bytes:
    """Load secret key for HMAC signing."""
    try:
        with open(SECRET_KEY_PATH, "rb") as f:
            return f.read(32)
    except FileNotFoundError:
        return b""


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

    def send(
        self,
        from_agent: str,
        to_agent: str,
        payload: dict[str, Any],
        conversation_id: str | None = None,
        message_type: str = "request",
    ) -> dict[str, Any]:
        """Send a message to another agent with Phase 2 security."""
        data: dict[str, Any] = {
            "from": from_agent,
            "to": to_agent,
            "payload": payload,
            "conversation_id": conversation_id,
            "message_type": message_type,
        }

        # Phase 2: Add security fields if secret key available
        secret_key = _load_secret_key()
        if secret_key:
            # Generate nonce and timestamp
            nonce = secrets.token_hex(16)
            timestamp = int(time.time())

            data["nonce"] = nonce
            data["timestamp"] = timestamp

            # Generate HMAC signature (sort keys for determinism)
            payload_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
            signature = hmac.new(
                secret_key,
                payload_str.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            data["hmac_signature"] = signature

        return self._send_request("ipc_send", data)

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

    def list_services(self, include_offline: bool = False) -> dict[str, Any]:
        """List registered services only."""
        return self._send_request("service_list", {
            "include_offline": include_offline,
        })

    def search_registry(
        self,
        query: str,
        source: str = "all",
        fuzzy: bool = True,
        include_offline: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search registry entries with fuzzy matching."""
        return self._send_request("registry_search", {
            "query": query,
            "source": source,
            "fuzzy": fuzzy,
            "include_offline": include_offline,
            "limit": limit,
        })

    def ping(self) -> bool:
        """Check if daemon is alive."""
        try:
            response = self._send_request("ping", {})
            return response.get("status") in ("ok", "pong")
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        """Get IPC daemon status including queue statistics."""
        return self._send_request("ipc_status", {})


# Alias for backward compatibility with agentctl
BrainDaemonClient = DaemonClient
