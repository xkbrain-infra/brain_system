#!/usr/bin/env python3
"""brain-manager 专属 checker: 约束 planning 文档的写入路径。"""

from __future__ import annotations

from typing import Iterator

from result import CheckContext, CheckResult


TASKS_ROOT = "/xkagent_infra/runtime/tasks/"
GROUPS_PENDING_MARKER = "/pending/"
GROUPS_ROOT = "/xkagent_infra/groups/"
UPDATE_BRAIN_PENDING = "/xkagent_infra/runtime/update_brain/pending/"

OVERRIDE_META = {
    "gate_id": "G-MANAGER-WRITE-PATH",
    "description": "manager 只能把 planning 文档写到 runtime/tasks，不得写 groups pending 或 publish batch",
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


def _extract_targets(tool_input: dict) -> list[str]:
    keys = ("file_path", "path", "target_file", "dest", "destination")
    targets: list[str] = []
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            targets.append(value.strip())
    for text in _iter_strings(tool_input):
        if text.startswith("/xkagent_infra/"):
            targets.append(text.strip())
    deduped: list[str] = []
    seen = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        deduped.append(target)
    return deduped


def _message(target: str, reason: str) -> str:
    return (
        "🚫 Manager 的 planning 文档写入路径不合规 (G-MANAGER-WRITE-PATH)\n"
        f"路径: {target}\n"
        f"原因: {reason}\n\n"
        "Manager 只允许：\n"
        f"- 在 {TASKS_ROOT}<task_id>/ 下写 `INTAKE.md`、`contract.yaml`、`task_split.yaml`\n"
        "- 用 task_manager / IPC 做编排\n\n"
        "Manager 禁止：\n"
        "- 写 `groups/**/pending/**`\n"
        f"- 写 `{UPDATE_BRAIN_PENDING}<batch>/` 作为自己的 planning 产物\n"
    )


def check(context: CheckContext) -> CheckResult:
    if context.tool_name not in {"Write", "Edit"}:
        return CheckResult.pass_check()

    targets = _extract_targets(context.tool_input or {})
    for target in targets:
        if GROUPS_ROOT in target and GROUPS_PENDING_MARKER in target:
            return CheckResult.block(
                "G-MANAGER-WRITE-PATH",
                _message(target, "groups 项目目录不是 manager 的 planning 工作区"),
                "CRITICAL",
            )
        if UPDATE_BRAIN_PENDING in target:
            return CheckResult.block(
                "G-MANAGER-WRITE-PATH",
                _message(target, "publish batch 属于执行角色的交付批次，不是 manager 的 planning 文档目录"),
                "CRITICAL",
            )

    return CheckResult.pass_check()
