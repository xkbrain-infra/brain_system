"""MCP Server for brain_task_manager — IPC bridge to resident service.

Forwards all tool calls to `service-brain_task_manager` via brain_ipc.
Does NOT access YAML files directly; the resident service owns all state.

Usage (stdio transport):
    python3 mcp_server.py

Env vars:
    MCP_AGENT_NAME          — identity used for IPC (default: mcp-brain_task_manager)
    TASK_MANAGER_SERVICE    — target service name (default: service-brain_task_manager)
    DAEMON_SOCKET           — brain_ipc socket path (default: /tmp/brain_ipc.sock)
    TASK_MANAGER_TIMEOUT_S  — request timeout in seconds (default: 15)
"""

import asyncio
import json
import os
import sys
import time
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
from ipc_client import DaemonClient  # noqa: E402

MCP_NAME       = os.environ.get("MCP_AGENT_NAME",       "mcp-brain_task_manager")
TARGET_SERVICE = os.environ.get("TASK_MANAGER_SERVICE", "service-brain_task_manager")
SOCKET_PATH    = os.environ.get("DAEMON_SOCKET",        "/tmp/brain_ipc.sock")
TIMEOUT_S      = float(os.environ.get("TASK_MANAGER_TIMEOUT_S", "15"))
POLL_INTERVAL  = 0.1

server = Server("brain-task-manager")
daemon = DaemonClient(SOCKET_PATH)


# ── IPC bridge ────────────────────────────────────────────────────────────────

async def ipc_request(payload: dict) -> dict:
    """Send a payload to service-brain_task_manager and wait for response."""
    conversation_id = f"btm:{uuid.uuid4()}"

    try:
        await asyncio.to_thread(
            daemon.register_service,
            MCP_NAME,
            {"type": "mcp_client", "target_service": TARGET_SERVICE},
        )
    except Exception:
        pass

    await asyncio.to_thread(
        daemon.send,
        from_agent=MCP_NAME,
        to_agent=TARGET_SERVICE,
        payload=payload,
        conversation_id=conversation_id,
        message_type="request",
    )

    deadline = time.monotonic() + TIMEOUT_S
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
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    pass
            return data if isinstance(data, dict) else {"error": "invalid payload", "raw": str(data)}
        await asyncio.sleep(POLL_INTERVAL)

    return {"status": "error", "error": f"timeout after {TIMEOUT_S:.0f}s waiting for {TARGET_SERVICE}"}


# ── Tool definitions ──────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [

        # ── Project ──────────────────────────────────────────────────────────

        Tool(
            name="project_create",
            description=(
                "Create a new project. Automatically creates an intake task for kickoff. "
                "Returns project_id and intake_task_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Unique project ID, e.g. BS-027"},
                    "group":      {"type": "string", "description": "Team/group name, e.g. brain_system"},
                    "title":      {"type": "string", "description": "Project title"},
                    "owner":      {"type": "string", "description": "PMO agent name (accountable owner)"},
                },
                "required": ["project_id", "group", "title", "owner"],
            },
        ),

        Tool(
            name="project_progress",
            description=(
                "Advance a project to the next stage (must be sequential). "
                "Stages: S1_alignment → S2_requirements → S3_research → S4_analysis "
                "→ S5_solution → S6_tasks → S7_verification → S8_complete."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id":   {"type": "string"},
                    "target_stage": {
                        "type": "string",
                        "enum": ["S2_requirements", "S3_research", "S4_analysis",
                                 "S5_solution", "S6_tasks", "S7_verification",
                                 "S8_complete", "archived"],
                    },
                },
                "required": ["project_id", "target_stage"],
            },
        ),

        Tool(
            name="project_query",
            description="Query projects with optional filters. All fields optional (omit = no filter).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Exact project ID"},
                    "group":      {"type": "string", "description": "Filter by group"},
                    "stage":      {
                        "type": "string",
                        "description": "Filter by stage",
                        "enum": ["S1_alignment", "S2_requirements", "S3_research", "S4_analysis",
                                 "S5_solution", "S6_tasks", "S7_verification", "S8_complete", "archived"],
                    },
                },
            },
        ),

        Tool(
            name="project_dependency_set",
            description=(
                "Set upstream dependencies for a project. Cycle detection is enforced. "
                "Overwrites any existing dependency list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of upstream project_ids this project depends on",
                    },
                },
                "required": ["project_id", "depends_on"],
            },
        ),

        Tool(
            name="project_dependency_query",
            description="Query upstream and downstream dependencies of a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
                "required": ["project_id"],
            },
        ),

        # ── Task ─────────────────────────────────────────────────────────────

        Tool(
            name="task_create",
            description=(
                "Create a new task under a project. "
                "Required: task_id, project_id, group, title, owner. "
                "Task starts in 'pending' status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id":           {"type": "string", "description": "Unique task ID, e.g. BS-027-T001"},
                    "project_id":        {"type": "string"},
                    "group":             {"type": "string"},
                    "title":             {"type": "string"},
                    "owner":             {"type": "string", "description": "Accountable agent"},
                    "priority":          {"type": "string", "enum": ["critical", "high", "normal", "low"], "default": "normal"},
                    "description":       {"type": "string"},
                    "deadline":          {"type": "string", "description": "ISO8601, e.g. 2026-04-01T00:00:00Z"},
                    "trigger_policy":    {"type": "string", "enum": ["manual", "auto", "scheduled"], "default": "manual"},
                    "review_by":         {"type": "string", "description": "Designated reviewer agent"},
                    "depends_on":        {"type": "array", "items": {"type": "string"}, "description": "task_ids this task depends on"},
                    "todo_list":         {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "done": {"type": "boolean", "default": False},
                            },
                            "required": ["text"],
                        },
                    },
                    "tags":              {"type": "array", "items": {"type": "string"}},
                    "participants":      {"type": "array", "items": {"type": "string"}},
                    "escalation_policy": {"type": "string"},
                    "next_check_at":     {"type": "string", "description": "ISO8601"},
                },
                "required": ["task_id", "project_id", "group", "title", "owner"],
            },
        ),

        Tool(
            name="task_update",
            description=(
                "Update a task's fields or advance its status through the FSM. "
                "FSM transitions: pending→ready→in_progress→review→verified→completed. "
                "Blocked is a recoverable side state. Use expected_version for optimistic locking."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id":          {"type": "string"},
                    "expected_version": {"type": "integer", "description": "CAS lock — omit to skip version check"},
                    "status":           {
                        "type": "string",
                        "enum": ["pending", "ready", "in_progress", "review",
                                 "verified", "completed", "failed", "cancelled",
                                 "blocked", "archived"],
                    },
                    "worker_id":         {"type": "string", "description": "Executing agent (set when status→in_progress)"},
                    "blocked_reason":    {"type": "string", "description": "Required when status→blocked"},
                    "result":            {"type": "string", "description": "Summary when status→completed or failed"},
                    "last_log_ref":      {"type": "string"},
                    "owner":             {"type": "string"},
                    "priority":          {"type": "string", "enum": ["critical", "high", "normal", "low"]},
                    "title":             {"type": "string"},
                    "description":       {"type": "string"},
                    "deadline":          {"type": "string"},
                    "review_by":         {"type": "string"},
                    "next_check_at":     {"type": "string"},
                    "escalation_policy": {"type": "string"},
                    "artifact_refs":     {"type": "array", "items": {"type": "string"}},
                    "participants":      {"type": "array", "items": {"type": "string"}},
                    "todo_list":         {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "done": {"type": "boolean"},
                            },
                        },
                    },
                    "depends_on":        {"type": "array", "items": {"type": "string"}},
                    "tags":              {"type": "array", "items": {"type": "string"}},
                    "note":              {"type": "string", "description": "Written to event log"},
                },
                "required": ["task_id"],
            },
        ),

        Tool(
            name="task_query",
            description="Query tasks with optional filters. All fields optional.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id":    {"type": "string", "description": "Exact task ID"},
                    "project_id": {"type": "string"},
                    "group":      {"type": "string"},
                    "status":     {
                        "type": "string",
                        "enum": ["pending", "ready", "in_progress", "review",
                                 "verified", "completed", "failed", "cancelled",
                                 "blocked", "archived"],
                    },
                    "owner":      {"type": "string"},
                },
            },
        ),

        Tool(
            name="task_delete",
            description="Soft-delete a task (marks inactive, not physically removed).",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),

        Tool(
            name="task_stats",
            description="Get task statistics for a project: total count, breakdown by status and priority.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
                "required": ["project_id"],
            },
        ),

        Tool(
            name="task_pipeline_check",
            description=(
                "Validate a project's task dependency graph: "
                "detects cycles, missing dependencies, and counts ready/blocked tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
                "required": ["project_id"],
            },
        ),
    ]


# ── Tool dispatch ─────────────────────────────────────────────────────────────

_TOOL_TO_EVENT = {
    "project_create":            "PROJECT_CREATE",
    "project_progress":          "PROJECT_PROGRESS",
    "project_query":             "PROJECT_QUERY",
    "project_dependency_set":    "PROJECT_DEPENDENCY_SET",
    "project_dependency_query":  "PROJECT_DEPENDENCY_QUERY",
    "task_create":               "TASK_CREATE",
    "task_update":               "TASK_UPDATE",
    "task_query":                "TASK_QUERY",
    "task_delete":               "TASK_DELETE",
    "task_stats":                "TASK_STATS",
    "task_pipeline_check":       "TASK_PIPELINE_CHECK",
}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    event_type = _TOOL_TO_EVENT.get(name)
    if not event_type:
        result = {"status": "error", "error": f"unknown tool: {name}"}
    else:
        payload = {"event_type": event_type, **arguments}
        result = await ipc_request(payload)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
