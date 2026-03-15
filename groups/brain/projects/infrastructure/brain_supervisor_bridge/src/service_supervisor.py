#!/usr/bin/env python3
"""IPC bridge service for supervisord.

Registers as `service-supervisor` so supervisor state is visible in IPC.
Supports simple IPC request actions:
- ping
- status: returns parsed `supervisorctl status`
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from typing import Any

import sys
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
from ipc_client import DaemonClient, NotifyClient  # noqa: E402

SERVICE_NAME = "service-brain_supervisor_bridge"
DEFAULT_SOCKET = "/tmp/brain_ipc.sock"
HEARTBEAT_INTERVAL = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(SERVICE_NAME)


class SupervisorBridgeService:
    def __init__(self, socket_path: str = DEFAULT_SOCKET) -> None:
        self._daemon = DaemonClient(socket_path)
        self._notify = NotifyClient(SERVICE_NAME)
        self._running = True

    def _handle_signal(self, *_: Any) -> None:
        self._running = False

    @staticmethod
    def _parse_supervisor_status(stdout: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            rows.append({
                "name": parts[0],
                "state": parts[1],
                "raw": line,
            })
        return rows

    def _get_supervisor_status(self) -> dict[str, Any]:
        proc = subprocess.run(
            ["supervisorctl", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "code": proc.returncode,
                "stderr": (proc.stderr or "").strip(),
                "stdout": (proc.stdout or "").strip(),
            }
        rows = self._parse_supervisor_status(proc.stdout)
        return {
            "ok": True,
            "count": len(rows),
            "services": rows,
        }

    @staticmethod
    def _normalize_payload(payload: Any) -> dict[str, Any]:
        """Normalize incoming payload from various IPC senders.

        Supported shapes:
        - {"action": "..."}
        - {"content": "{\"action\":\"status\"}"}
        - {"message": "{\"action\":\"status\"}"}
        - "{\"action\":\"status\"}"
        """
        if isinstance(payload, dict) and "action" in payload:
            return payload

        if isinstance(payload, dict):
            for key in ("content", "message", "text"):
                value = payload.get(key)
                if isinstance(value, str):
                    try:
                        decoded = json.loads(value)
                        if isinstance(decoded, dict):
                            return decoded
                    except json.JSONDecodeError:
                        continue
            return payload

        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                return {}
        return {}

    def _handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_payload(payload)
        action = payload.get("action", "")
        if action == "ping":
            return {"status": "ok", "service": SERVICE_NAME, "ts": time.time()}
        if action == "status":
            result = self._get_supervisor_status()
            return {"status": "ok" if result.get("ok") else "error", "action": action, "result": result}
        return {
            "status": "error",
            "error": f"Unknown action: '{action}'. Valid: ping, status",
        }

    async def _process_message(self, msg: dict[str, Any]) -> None:
        from_agent = msg.get("from", "")
        conversation_id = msg.get("conversation_id")
        message_type = msg.get("message_type", "request")
        payload = msg.get("payload", {})

        # Avoid response loops: this service only handles request messages.
        if message_type != "request":
            return

        try:
            response = await asyncio.to_thread(self._handle_request, payload)
        except Exception as exc:  # defensive
            response = {"status": "error", "error": str(exc)}

        try:
            await asyncio.to_thread(
                self._daemon.send,
                from_agent=SERVICE_NAME,
                to_agent=from_agent,
                payload=response,
                conversation_id=conversation_id,
                message_type="response",
            )
        except Exception as exc:
            logger.error("reply failed: %s", exc)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self._daemon.service_heartbeat, SERVICE_NAME)
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _message_loop(self) -> None:
        async for _event in self._notify.listen():
            if not self._running:
                break
            try:
                result = await asyncio.to_thread(
                    self._daemon.recv,
                    SERVICE_NAME,
                    "auto",
                    None,
                    20,
                )
                messages = result.get("messages", [])
                for msg in messages:
                    await self._process_message(msg)
            except Exception as exc:
                logger.error("recv failed: %s", exc)
                await asyncio.sleep(1)

    async def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        await asyncio.to_thread(
            self._daemon.register_service,
            SERVICE_NAME,
            {"type": "supervisor_bridge", "version": "1.0.0"},
        )
        logger.info("registered %s", SERVICE_NAME)

        await asyncio.gather(self._heartbeat_loop(), self._message_loop())


def main() -> None:
    socket_path = os.environ.get("DAEMON_SOCKET", DEFAULT_SOCKET)
    service = SupervisorBridgeService(socket_path)
    asyncio.run(service.run())


if __name__ == "__main__":
    main()
