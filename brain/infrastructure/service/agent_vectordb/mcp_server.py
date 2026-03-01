"""MCP Server for agent_vectordb/brain_docs — IPC bridge to resident service.

This MCP server does not query DB directly. It forwards all tool calls to the
resident IPC service `service-agent_vectordb` so every agent shares one backend.
"""

import asyncio
import json
import os
import time
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import sys
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
from ipc_client import DaemonClient  # noqa: E402

MCP_NAME = os.environ.get("MCP_AGENT_NAME", "mcp-agent_vectordb")
TARGET_SERVICE = os.environ.get("VECTORDB_SERVICE_NAME", "service-agent_vectordb")
SOCKET_PATH = os.environ.get("DAEMON_SOCKET", "/tmp/brain_ipc.sock")
REQUEST_TIMEOUT_S = float(os.environ.get("VECTORDB_IPC_TIMEOUT_S", "10"))
POLL_INTERVAL_S = 0.1

server = Server("agent-vectordb")
daemon = DaemonClient(SOCKET_PATH)


async def ipc_request(action: str, payload: dict) -> dict:
    """Send request to resident service and wait for response by conversation_id."""
    conversation_id = f"vectordb:{uuid.uuid4()}"

    try:
        await asyncio.to_thread(
            daemon.register,
            MCP_NAME,
            {"type": "mcp_client", "target_service": TARGET_SERVICE},
        )
    except Exception:
        # Best effort only; daemon may already discover this instance.
        pass

    await asyncio.to_thread(
        daemon.send,
        from_agent=MCP_NAME,
        to_agent=TARGET_SERVICE,
        payload={"action": action, **payload},
        conversation_id=conversation_id,
        message_type="request",
    )

    deadline = time.monotonic() + REQUEST_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = await asyncio.to_thread(
            daemon.recv,
            MCP_NAME,
            "auto",
            conversation_id,
            1,
        )
        messages = resp.get("messages", [])
        if messages:
            data = messages[0].get("payload", {})
            if isinstance(data, dict):
                return data
            return {"status": "error", "error": f"invalid payload from {TARGET_SERVICE}"}
        await asyncio.sleep(POLL_INTERVAL_S)

    return {
        "status": "error",
        "error": f"timeout waiting {REQUEST_TIMEOUT_S:.1f}s for {TARGET_SERVICE}",
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="doc_query",
            description="Search documents by keyword, domain (spec/wf/knlg/evo), category, or tags. Returns matching documents with metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search in title/description/id"},
                    "domain": {
                        "type": "string",
                        "description": "Domain filter, e.g. spec/wf/knlg/evo/skill/group",
                    },
                    "category": {"type": "string", "description": "CORE, POLICY, STANDARD, TEMPLATE, etc."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="doc_get",
            description="Get a document by its exact ID (e.g. G-SPEC-CORE-LAYERS).",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID"},
                },
                "required": ["doc_id"],
            },
        ),
        Tool(
            name="doc_related",
            description="Find documents related to a given document ID using vector similarity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Source document ID"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["doc_id"],
            },
        ),
        Tool(
            name="doc_search",
            description="Semantic search across all documents using natural language query. Requires embedding service.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "doc_query":
        results = await ipc_request(
            "query",
            {
                "keyword": arguments.get("keyword"),
                "domain": arguments.get("domain"),
                "category": arguments.get("category"),
                "tags": arguments.get("tags"),
                "limit": arguments.get("limit", 20),
            },
        )
    elif name == "doc_get":
        results = await ipc_request("get", {"doc_id": arguments["doc_id"]})
    elif name == "doc_related":
        results = await ipc_request(
            "related",
            {"doc_id": arguments["doc_id"], "limit": arguments.get("limit", 5)},
        )
    elif name == "doc_search":
        results = await ipc_request(
            "search",
            {"query": arguments["query"], "limit": arguments.get("limit", 10)},
        )
    else:
        results = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
