#!/usr/bin/env python3
"""brain-manager 专属 checker: 构建前检查 pending/MANIFEST.yaml

作为 BaseChecker 子类，由全局 handler.py 的 overrides 机制自动加载。
不需要独立的 pre_tool_use 入口脚本。
"""

import os
from pathlib import Path

# 在 handler.py 加载时，sys.path 已包含 lep/ 和 checkers/
from result import CheckResult, CheckContext


PENDING_DIR = "/brain/runtime/update_brain/pending"
MANIFEST_PATH = os.path.join(PENDING_DIR, "MANIFEST.yaml")
UPDATE_BRAIN_SPEC = "/brain/base/workflow/operations/update_brain.yaml"

# 触发检查的 tool 关键词
BUILD_KEYWORDS = ["deploy_publish", "deploy_merge", "deploy_build", "deploy_deploy"]

# override 元数据（handler.py 用这些字段决定何时调用）
OVERRIDE_META = {
    "gate_id": "G-PENDING-CHECK",
    "description": "构建前检查 pending 是否有未处理的更新",
    "triggers": {
        "tool_keywords": BUILD_KEYWORDS,
    },
}


def check(context: CheckContext) -> CheckResult:
    """当调用构建类工具时，检查 pending 是否有未处理文件。

    Returns:
        CheckResult: warn if pending exists, pass otherwise
    """
    tool_name = context.tool_name

    # 只在调用构建类工具时检查
    is_build_tool = any(kw in tool_name.lower() for kw in BUILD_KEYWORDS)
    if not is_build_tool:
        return CheckResult.pass_check()

    if not os.path.isfile(MANIFEST_PATH):
        return CheckResult.pass_check()

    try:
        import yaml
        with open(MANIFEST_PATH) as f:
            manifest = yaml.safe_load(f)

        if not manifest:
            return CheckResult.pass_check()

        files = manifest.get("files", [])
        if not files:
            return CheckResult.pass_check()

        batch_id = manifest.get("batch_id", "unknown")
        submitted_by = manifest.get("submitted_by", "unknown")
        file_count = len(files)

        file_list = "\n".join(
            f"  - {f.get('source', '?')} -> {f.get('target', '?')}"
            for f in files[:5]
        )
        if file_count > 5:
            file_list += f"\n  ... +{file_count - 5} more"

        msg = (
            f"⚠️ G-PENDING-CHECK: 发现未处理的 pending 更新！\n"
            f"\n"
            f"  batch_id: {batch_id}\n"
            f"  submitted_by: {submitted_by}\n"
            f"  文件数: {file_count}\n"
            f"{file_list}\n"
            f"\n"
            f"请先按操作手册处理 pending（Step 1-3），再执行构建。\n"
            f"操作规范: {UPDATE_BRAIN_SPEC}"
        )

        return CheckResult.warn("G-PENDING-CHECK", msg, "HIGH")

    except Exception as e:
        return CheckResult.warn(
            "G-PENDING-CHECK",
            f"⚠️ G-PENDING-CHECK: pending/MANIFEST.yaml 读取失败: {e}",
            "MEDIUM"
        )
