#!/usr/bin/env python3
"""Service Agent VectorDB - IPC-accessible document database query service.

Registers as 'service-brain_vectordb' in brain_ipc, listens for query requests
via IPC, and returns results. Any agent or service can query docs by sending
an IPC message to 'service-brain_vectordb'.

IPC Request payload format:
    {
        "action": "query" | "get" | "related" | "search",
        # For "query":
        "keyword": "...",
        "domain": "spec" | "wf" | "knlg" | "evo",
        "category": "CORE" | "POLICY" | ...,
        "tags": ["..."],
        "limit": 20,
        # For "get":
        "doc_id": "G-SPEC-CORE-LAYERS",
        # For "related":
        "doc_id": "G-SPEC-CORE-LAYERS",
        "limit": 5,
        # For "search":
        "query": "如何排查 IPC 超时",
        "limit": 10,
    }

IPC Response payload format:
    {
        "status": "ok" | "error",
        "action": "...",
        "results": [...] | {...},
        "error": "..." (only when status=error)
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# IPC client
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
from ipc_client import DaemonClient, NotifyClient  # noqa: E402

# Agent VectorDB queries
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/agent_vectordb/releases/v1.0.0")
from src import queries  # noqa: E402

SERVICE_NAME = "service-brain_vectordb"
DEFAULT_SOCKET = "/tmp/brain_ipc.sock"
DEFAULT_HEALTH_PORT = 8094
HEARTBEAT_INTERVAL = 5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(SERVICE_NAME)

_HEALTH_STATE: dict[str, Any] = {
    "status": "starting",
    "service": SERVICE_NAME,
    "requests_handled": 0,
    "last_request_ts": None,
    "errors": 0,
}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(_HEALTH_STATE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


async def handle_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a query request and return response payload."""
    action = payload.get("action", "")

    if action == "query":
        results = await queries.query_docs(
            keyword=payload.get("keyword"),
            domain=payload.get("domain"),
            category=payload.get("category"),
            tags=payload.get("tags"),
            limit=payload.get("limit", 20),
        )
        return {"status": "ok", "action": action, "results": results}

    elif action == "get":
        doc_id = payload.get("doc_id")
        if not doc_id:
            return {"status": "error", "action": action, "error": "doc_id required"}
        result = await queries.get_doc_by_id(doc_id)
        if result is None:
            return {"status": "error", "action": action, "error": f"Document '{doc_id}' not found"}
        return {"status": "ok", "action": action, "results": result}

    elif action == "related":
        doc_id = payload.get("doc_id")
        if not doc_id:
            return {"status": "error", "action": action, "error": "doc_id required"}
        results = await queries.get_related(
            doc_id=doc_id,
            limit=payload.get("limit", 5),
        )
        return {"status": "ok", "action": action, "results": results}

    elif action == "search":
        query_text = payload.get("query")
        if not query_text:
            return {"status": "error", "action": action, "error": "query required"}
        results = await queries.semantic_search(
            query=query_text,
            limit=payload.get("limit", 10),
        )
        return {"status": "ok", "action": action, "results": results}

    else:
        return {
            "status": "error",
            "action": action,
            "error": f"Unknown action: '{action}'. Valid: query, get, related, search",
        }


class ServiceAgentVectorDB:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        health_port: int = DEFAULT_HEALTH_PORT,
    ) -> None:
        self._daemon = DaemonClient(socket_path)
        self._notify = NotifyClient(SERVICE_NAME)
        self._health_port = health_port
        self._running = True

    def _handle_signal(self, *_: Any) -> None:
        logger.info("Shutdown requested")
        self._running = False

    def _start_health_server(self) -> None:
        server = HTTPServer(("0.0.0.0", self._health_port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Health server on port %s", self._health_port)

    async def _process_message(self, msg: dict[str, Any]) -> None:
        """Process a single IPC message and send reply."""
        msg_id = msg.get("id", "")
        from_agent = msg.get("from", "")
        payload = msg.get("payload", {})
        conversation_id = msg.get("conversation_id")

        logger.info("Request from %s: action=%s", from_agent, payload.get("action", "?"))

        try:
            response = await handle_request(payload)
        except Exception as e:
            logger.error("Handler error: %s", e)
            response = {"status": "error", "error": str(e)}
            _HEALTH_STATE["errors"] = _HEALTH_STATE.get("errors", 0) + 1

        # Send reply
        try:
            await asyncio.to_thread(
                self._daemon.send,
                from_agent=SERVICE_NAME,
                to_agent=from_agent,
                payload=response,
                conversation_id=conversation_id,
                message_type="response",
            )
        except Exception as e:
            logger.error("Reply send failed: %s", e)

        _HEALTH_STATE["requests_handled"] = _HEALTH_STATE.get("requests_handled", 0) + 1
        _HEALTH_STATE["last_request_ts"] = time.time()

    async def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self._start_health_server()

        # Register service
        try:
            await asyncio.to_thread(
                self._daemon.register_service,
                SERVICE_NAME,
                {"type": "agent_vectordb", "version": "1.0"},
            )
            logger.info("Registered as '%s'", SERVICE_NAME)
        except Exception as e:
            logger.error("Registration failed: %s (will retry via recv loop)", e)

        _HEALTH_STATE["status"] = "ok"

        # Run heartbeat and message loop concurrently
        await asyncio.gather(
            self._heartbeat_loop(),
            self._message_loop(),
        )
        logger.info("Service stopped")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat to daemon."""
        while self._running:
            try:
                await asyncio.to_thread(
                    self._daemon.service_heartbeat, SERVICE_NAME
                )
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _message_loop(self) -> None:
        """Listen for notifications, then recv + process."""
        async for _event in self._notify.listen():
            if not self._running:
                break

            try:
                result = await asyncio.to_thread(
                    self._daemon.recv,
                    SERVICE_NAME,
                    ack_mode="auto",
                    max_items=10,
                )
                messages = result.get("messages", [])
                for msg in messages:
                    await self._process_message(msg)
            except Exception as e:
                logger.error("Recv error: %s", e)
                await asyncio.sleep(1)


def main() -> None:
    health_port = int(os.environ.get("AGENT_VECTORDB_HEALTH_PORT", DEFAULT_HEALTH_PORT))
    socket_path = os.environ.get("DAEMON_SOCKET", DEFAULT_SOCKET)

    svc = ServiceAgentVectorDB(socket_path=socket_path, health_port=health_port)
    asyncio.run(svc.run())


if __name__ == "__main__":
    main()
