#!/usr/bin/env python3
"""Block direct sandbox lifecycle/bootstrap commands from brain manager.

manager 在 orchestrator workflow 中只负责 BOOTSTRAP_DISPATCH，不直接执行
sandboxctl create/start/stop/destroy/exec。真正执行者必须是 devops。
"""

from __future__ import annotations

import re

from result import CheckContext, CheckResult


OVERRIDE_META = {
    "gate_id": "G-MANAGER-SANDBOX-DELEGATION",
    "description": "manager 必须把 sandbox lifecycle/bootstrap 委托给 devops",
    "triggers": {
        "tool_names": ["Bash"],
    },
}

_LIFECYCLE_SUBCOMMANDS = {"create", "start", "stop", "destroy", "exec", "spawn-agent"}
_READ_ONLY_SUBCOMMANDS = {"list", "validate"}

_COMMAND_PATTERNS = (
    re.compile(
        r"(?<!\S)(?:/xkagent_infra/brain/bin/sandboxctl|sandboxctl)\s+"
        r"(create|start|stop|destroy|exec|spawn-agent|list|validate)\b"
    ),
    re.compile(
        r"(?<!\S)python3?\s+"
        r"(?:"
        r"/xkagent_infra/groups/brain/projects/base/sandbox/service/sandbox_service\.py|"
        r"/xkagent_infra/groups/brain/projects/infrastructure/brain_sandbox_service/src/current/sandbox_service\.py|"
        r"/xkagent_infra/brain/infrastructure/service/brain_sandbox_service/current/sandbox_service\.py"
        r")\s+"
        r"(create|start|stop|destroy|exec|spawn-agent|list|validate)\b"
    ),
)


def _extract_subcommand(command: str) -> str:
    for pattern in _COMMAND_PATTERNS:
        match = pattern.search(command or "")
        if match:
            return str(match.group(1) or "").strip().lower()
    return ""


def check(context: CheckContext) -> CheckResult:
    if (context.tool_name or "").strip() != "Bash":
        return CheckResult.pass_check()

    command = str(context.command or context.tool_input.get("command") or "")
    subcommand = _extract_subcommand(command)
    if not subcommand or subcommand in _READ_ONLY_SUBCOMMANDS:
        return CheckResult.pass_check()

    if subcommand not in _LIFECYCLE_SUBCOMMANDS:
        return CheckResult.pass_check()

    return CheckResult.block(
        "G-MANAGER-SANDBOX-DELEGATION",
        "\n".join(
            [
                "🚫 manager 不得直接执行 sandbox lifecycle/bootstrap。",
                "",
                f"检测到直接 sandbox 操作: {subcommand}",
                "",
                "正确流程：",
                "1. manager 生成 BOOTSTRAP_DISPATCH",
                "2. 通过 ipc_send / task_manager 把请求交给 agent-brain_devops",
                "3. 等待 devops 回 BOOTSTRAP_COMPLETE / BOOTSTRAP_FAILED",
                "",
                "manager 允许的 sandbox 相关操作：sandboxctl list / validate",
                "devops 执行的命令示例：",
                "  /xkagent_infra/brain/bin/sandboxctl create <project_id> --type development --with-agent orchestrator --pending-id <pending_id> [--model <provider/model>]",
            ]
        ),
        "CRITICAL",
    )
