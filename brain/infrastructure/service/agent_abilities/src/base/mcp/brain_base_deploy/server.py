#!/usr/bin/env python3
"""
brain_base_deploy MCP Server
Exclusive to agent-brain-manager. Wraps the agent_abilities build system.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

BUILD_SH = Path("/brain/infrastructure/service/agent_abilities/build/build.sh")
TARGETS = ["spec", "workflow", "knowledge", "evolution", "skill", "hooks", "mcp_server", "index", "docs", "all"]

app = Server("brain_base_deploy")


def run_build(args: list[str], timeout: int = 120) -> str:
    result = subprocess.run(
        ["bash", str(BUILD_SH)] + args,
        capture_output=True, text=True, timeout=timeout
    )
    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr
    return output.strip()


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="deploy_diff",
            description="Show diff between /brain/base/ (deployed) and src/ (source). "
                        "Use to check what's out of sync before publishing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": f"Build target. One of: {', '.join(TARGETS)}. Omit for all docs.",
                        "enum": TARGETS
                    }
                }
            }
        ),
        Tool(
            name="deploy_publish",
            description="Full pipeline: diff → merge (base→src) → build → deploy to /brain/base/. "
                        "This is the main deploy command.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": f"Build target. One of: {', '.join(TARGETS)}.",
                        "enum": TARGETS
                    },
                    "auto_merge": {
                        "type": "boolean",
                        "description": "Auto-confirm merge step without prompting (default: true).",
                        "default": True
                    }
                },
                "required": ["target"]
            }
        ),
        Tool(
            name="deploy_merge",
            description="Merge changes from /brain/base/ back into src/ (base→src direction). "
                        "Use when files were edited directly in /brain/base/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": f"Build target. One of: {', '.join(TARGETS)}.",
                        "enum": TARGETS
                    }
                },
                "required": ["target"]
            }
        ),
        Tool(
            name="deploy_versions",
            description="List all published release versions with timestamps and included domains.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="deploy_rollback",
            description="Roll back /brain/base/ to a previously released version.",
            inputSchema={
                "type": "object",
                "properties": {
                    "version": {
                        "type": "string",
                        "description": "Version to roll back to, e.g. '2.0.0' or '2.1.0'."
                    }
                },
                "required": ["version"]
            }
        ),
        Tool(
            name="deploy_stats",
            description="Generate spec/LEP/hooks coverage statistics and write to knowledge base.",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "deploy_diff":
            target = arguments.get("target", "docs")
            output = run_build(["diff", target])

        elif name == "deploy_publish":
            target = arguments["target"]
            auto_merge = arguments.get("auto_merge", True)
            if auto_merge:
                proc = subprocess.run(
                    ["bash", str(BUILD_SH), "publish", target],
                    input="y\n", capture_output=True, text=True, timeout=300
                )
                output = proc.stdout
                if proc.stderr:
                    output += "\n[stderr]\n" + proc.stderr
                output = output.strip()
            else:
                output = run_build(["publish", target], timeout=300)

        elif name == "deploy_merge":
            target = arguments["target"]
            proc = subprocess.run(
                ["bash", str(BUILD_SH), "merge", target],
                input="y\n", capture_output=True, text=True, timeout=120
            )
            output = proc.stdout
            if proc.stderr:
                output += "\n[stderr]\n" + proc.stderr
            output = output.strip()

        elif name == "deploy_versions":
            output = run_build(["versions"])

        elif name == "deploy_rollback":
            version = arguments["version"]
            output = run_build(["rollback", version], timeout=120)

        elif name == "deploy_stats":
            output = run_build(["stats"], timeout=120)

        else:
            output = f"Unknown tool: {name}"

    except subprocess.TimeoutExpired:
        output = f"Error: command timed out"
    except Exception as e:
        output = f"Error: {e}"

    return [TextContent(type="text", text=output)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
