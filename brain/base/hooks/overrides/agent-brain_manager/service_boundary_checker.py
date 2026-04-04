#!/usr/bin/env python3
"""brain-manager 专属 checker: 禁止通过 published service 目录做架构探索。"""

from __future__ import annotations

from typing import Iterator
import re

from result import CheckContext, CheckResult


BLOCKED_PREFIXES = (
    "/xkagent_infra/brain/infrastructure/service/",
    "/xkagent_infra/groups/brain/projects/infrastructure/",
    "/xkagent_infra/groups/brain/projects/base/sandbox/service/",
    "/xkagent_infra/groups/brain/platform/sandbox/",
)
ALLOWED_SERVICE_SEGMENTS = ("/config/",)
BLOCKED_TOOL_NAMES = {"Read", "Glob", "Grep", "Bash"}
WORKFLOW_CORE = "/brain/base/workflow/orchestrator_project_coding/workflow_core.yaml"
INIT_PHASE = "/brain/base/workflow/orchestrator_project_coding/phases/0_init.yaml"
TASKS_ROOT = "/xkagent_infra/runtime/tasks"
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
    "gate_id": "G-MANAGER-WORKFLOW-FIRST",
    "description": "manager 不得通过 published service 目录理解系统",
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


def _normalize(text: str) -> str:
    return text.strip().strip("\"'")


def _is_blocked_service_target(text: str) -> bool:
    value = _normalize(text)
    if not any(prefix in value for prefix in BLOCKED_PREFIXES):
        return False
    if any(segment in value for segment in ALLOWED_SERVICE_SEGMENTS):
        return False
    return True


def _blocked_targets(context: CheckContext) -> list[str]:
    targets: list[str] = []
    for text in _iter_strings(context.tool_input):
        if _is_blocked_service_target(text):
            targets.append(_normalize(text))
    deduped: list[str] = []
    seen = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        deduped.append(target)
    return deduped


def _message(targets: list[str]) -> str:
    preview = "\n".join(f"路径: {target}" for target in targets[:3])
    if len(targets) > 3:
        preview += f"\n... 还有 {len(targets) - 3} 个目标"

    return (
        "🚫 Manager 不能通过 service/source/runtime 目录做架构探索 (G-MANAGER-WORKFLOW-FIRST)\n"
        f"{preview}\n\n"
        "当前任务必须先按 orchestrator workflow 执行，而不是先了解 service 实现。\n\n"
        "你现在应该做的是：\n"
        f"1. 先读取 {WORKFLOW_CORE}\n"
        f"2. 再读取 {INIT_PHASE}\n"
        "3. 显式判断这次 run 的 init 是否已完成\n"
        "4. 若 init 未完成：报 blocker / bootstrap 状态，不进入 intake/planning\n"
        f"5. 若 init 已完成：只在 {TASKS_ROOT}/<task_id>/ 下写 INTAKE/contract/task split\n"
        "6. 可用 agentctl 做 brain agent 生命周期管理\n"
        "7. 把 dashboard/service/sandbox 的实现任务派发给 dev 或 devops\n\n"
        "Manager 禁止：\n"
        "- 读取 published service、source service、sandbox runtime/instance 的实现或实例文件\n"
        "- 因为 owner 不在线就把实现任务改挂自己\n"
        "- 在 contract/task 已创建后继续做实现探索\n"
    )


def _is_allowed_manager_agentctl(command: str) -> bool:
    normalized = command.casefold()
    return any(re.search(pattern, normalized) for pattern in MANAGER_AGENTCTL_PATTERNS)


def check(context: CheckContext) -> CheckResult:
    if context.tool_name not in BLOCKED_TOOL_NAMES:
        return CheckResult.pass_check()

    if context.tool_name == "Bash":
        command = str((context.tool_input or {}).get("command") or "")
        if command.strip() and _is_allowed_manager_agentctl(command):
            return CheckResult.pass_check()

    targets = _blocked_targets(context)
    if not targets:
        return CheckResult.pass_check()

    return CheckResult.block("G-MANAGER-WORKFLOW-FIRST", _message(targets), "CRITICAL")
