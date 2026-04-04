#!/usr/bin/env python3
"""brain-manager 专属 checker: 阻止在 workflow 起手阶段做大范围探索。"""

from __future__ import annotations

import re
from typing import Iterator

from result import CheckContext, CheckResult


WORKFLOW_ROOT = "/xkagent_infra/brain/base/workflow/orchestrator_project_coding/"
WORKFLOW_CORE = "/brain/base/workflow/orchestrator_project_coding/workflow_core.yaml"
INIT_PHASE = "/brain/base/workflow/orchestrator_project_coding/phases/0_init.yaml"
TASKS_ROOT = "/xkagent_infra/runtime/tasks/"
RUNTIME_SANDBOX_ROOT = "/xkagent_infra/runtime/sandbox/"
TASK_MANAGER_ROOT = "/xkagent_infra/runtime/data/brain_task_manager/"
RUNTIME_LOGS_ROOT = "/xkagent_infra/runtime/logs/"
ALLOWED_ROOTS = (
    WORKFLOW_ROOT,
    TASKS_ROOT,
    RUNTIME_SANDBOX_ROOT,
    TASK_MANAGER_ROOT,
    RUNTIME_LOGS_ROOT,
    WORKFLOW_CORE,
    INIT_PHASE,
)
SEARCH_TOOLS = {"Glob", "Grep"}
READ_ONLY_BASH_PREFIXES = (
    "cat ",
    "sed ",
    "head ",
    "tail ",
    "awk ",
    "test ",
    "stat ",
    "wc ",
)
EXPLORATION_BASH_PATTERNS = (
    r"(^|\s)find(\s|$)",
    r"(^|\s)rg(\s|$)",
    r"(^|\s)grep(\s|$)",
    r"(^|\s)ls(\s|$)",
    r"(^|\s)tree(\s|$)",
    r"(^|\s)du(\s|$)",
    r"(^|\s)fd(\s|$)",
)
MANAGER_AGENTCTL_PATTERNS = (
    r"(?:^|[\s'\"=])(?:"
    r"/brain/infrastructure/service/agentctl/bin/agentctl|"
    r"/brain/infrastructure/service/agentctl/bin/brain-agentctl|"
    r"/xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl|"
    r"/xkagent_infra/brain/infrastructure/service/agentctl/bin/brain-agentctl|"
    r"agentctl|"
    r"brain-agentctl"
    r")(?=$|[\s'\"=])",
)

OVERRIDE_META = {
    "gate_id": "G-MANAGER-NO-EXPLORE",
    "description": "manager 在 workflow 起手阶段不得用搜索工具做架构探索",
}


def _iter_strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for sub_value in value.values():
            yield from _iter_strings(sub_value)
    elif isinstance(value, (list, tuple, set)):
        for sub_value in value:
            yield from _iter_strings(sub_value)


def _is_allowed_text(text: str) -> bool:
    return any(root in text for root in ALLOWED_ROOTS)


def _is_exploration_bash(command: str) -> bool:
    return any(re.search(pattern, command) for pattern in EXPLORATION_BASH_PATTERNS)


def _is_read_only_bash(command: str) -> bool:
    stripped = command.strip()
    return stripped.startswith(READ_ONLY_BASH_PREFIXES)


def _is_allowed_manager_agentctl(command: str) -> bool:
    normalized = command.casefold()
    return any(re.search(pattern, normalized) for pattern in MANAGER_AGENTCTL_PATTERNS)


def _search_message() -> str:
    return (
        "🚫 Manager 不能在 workflow 起手阶段使用 Glob/Grep/Explore 做架构探索 (G-MANAGER-NO-EXPLORE)\n\n"
        "你现在应该做的是：\n"
        f"1. 先读 {WORKFLOW_CORE}\n"
        f"2. 再读 {INIT_PHASE}\n"
        "3. 做 init 判定\n"
        "4. init 完成后，只在 runtime/tasks/<task>/ 下写 planning 文档，不做大范围搜索\n"
    )


def _bash_message() -> str:
    return (
        "🚫 Manager 不能用 Bash 做目录探索或架构排查 (G-MANAGER-NO-EXPLORE)\n\n"
        "Manager 现在只允许：\n"
        f"- 读取 {WORKFLOW_CORE}\n"
        f"- 读取 {INIT_PHASE}\n"
        f"- 定点读取 {RUNTIME_SANDBOX_ROOT} / {TASK_MANAGER_ROOT} / {RUNTIME_LOGS_ROOT} 下的证据文件\n"
        f"- 在 {TASKS_ROOT}<task_id>/ 下写 INTAKE / contract / task_split\n"
        "- 用 agentctl 做 brain agent 生命周期管理\n"
        "- 调用 task_manager / IPC 做编排\n"
    )


def check(context: CheckContext) -> CheckResult:
    if context.tool_name in SEARCH_TOOLS:
        texts = [text for text in _iter_strings(context.tool_input) if text.strip()]
        if not texts:
            return CheckResult.pass_check()
        if all(_is_allowed_text(text) for text in texts):
            return CheckResult.pass_check()
        return CheckResult.block("G-MANAGER-NO-EXPLORE", _search_message(), "CRITICAL")

    if context.tool_name == "Bash":
        command = str((context.tool_input or {}).get("command") or "")
        if not command.strip():
            return CheckResult.pass_check()
        if _is_allowed_manager_agentctl(command):
            return CheckResult.pass_check()
        if _is_exploration_bash(command):
            return CheckResult.block("G-MANAGER-NO-EXPLORE", _bash_message(), "CRITICAL")
        if _is_read_only_bash(command) and _is_allowed_text(command):
            return CheckResult.pass_check()
        if all(root not in command for root in ALLOWED_ROOTS):
            return CheckResult.block("G-MANAGER-NO-EXPLORE", _bash_message(), "CRITICAL")

    return CheckResult.pass_check()
