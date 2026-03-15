#!/usr/bin/env python3
"""brain-manager 专属 checker: 构建前检查 batch-based pending 目录。

作为 BaseChecker 子类，由全局 handler.py 的 overrides 机制自动加载。
不需要独立的 pre_tool_use 入口脚本。
"""

from pathlib import Path

# 在 handler.py 加载时，sys.path 已包含 lep/ 和 checkers/
from result import CheckContext, CheckResult


PENDING_DIR = Path("/xkagent_infra/runtime/update_brain/pending")
PROPOSALS_DIR = Path("/xkagent_infra/runtime/update_brain/proposals")
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


def _iter_batch_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _count_files(batch_dir: Path) -> int:
    return sum(1 for path in batch_dir.rglob("*") if path.is_file())


def _load_manifest(batch_dir: Path) -> tuple[str, str, int]:
    manifest_path = batch_dir / "MANIFEST.yaml"
    if not manifest_path.is_file():
        return batch_dir.name, "unknown", 0

    import yaml

    with manifest_path.open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle) or {}

    files = manifest.get("files") or []
    batch_id = str(manifest.get("batch_id") or batch_dir.name)
    submitted_by = str(manifest.get("submitted_by") or "unknown")
    return batch_id, submitted_by, len(files)


def _summarize_batches() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    active_batches: list[dict[str, object]] = []
    draft_only_batches: list[dict[str, object]] = []

    for batch_dir in _iter_batch_dirs(PENDING_DIR):
        has_base = (batch_dir / "base").is_dir()
        has_fixes = (batch_dir / "fixes").is_dir()
        has_manifest = (batch_dir / "MANIFEST.yaml").is_file()
        has_changelog = (batch_dir / "CHANGELOG.md").is_file()
        file_count = _count_files(batch_dir)

        if file_count == 0:
            continue

        batch_id, submitted_by, manifest_file_count = _load_manifest(batch_dir)
        summary = {
            "batch_dir": batch_dir.name,
            "batch_id": batch_id,
            "submitted_by": submitted_by,
            "file_count": file_count,
            "manifest_file_count": manifest_file_count,
            "has_base": has_base,
            "has_fixes": has_fixes,
            "has_manifest": has_manifest,
            "has_changelog": has_changelog,
        }

        if has_base or has_fixes or has_manifest:
            active_batches.append(summary)
        else:
            draft_only_batches.append(summary)

    return active_batches, draft_only_batches


def _format_batch_line(batch: dict[str, object]) -> str:
    flags: list[str] = []
    if batch["has_base"]:
        flags.append("base")
    if batch["has_fixes"]:
        flags.append("fixes")
    if batch["has_manifest"]:
        flags.append("manifest")
    if batch["has_changelog"]:
        flags.append("changelog")

    manifest_suffix = ""
    if batch["has_manifest"]:
        manifest_suffix = f", mapped={batch['manifest_file_count']}"

    return (
        f"  - {batch['batch_id']} "
        f"(dir={batch['batch_dir']}, flags={','.join(flags) or 'none'}, "
        f"files={batch['file_count']}{manifest_suffix}, by={batch['submitted_by']})"
    )


def check(context: CheckContext) -> CheckResult:
    """当调用构建类工具时，检查 pending 是否仍有待处理 batch。"""
    tool_name = (context.tool_name or "").lower()

    # 只在调用构建类工具时检查
    if not any(keyword in tool_name for keyword in BUILD_KEYWORDS):
        return CheckResult.pass_check()

    try:
        active_batches, draft_only_batches = _summarize_batches()
        if not active_batches and not draft_only_batches:
            return CheckResult.pass_check()

        lines = ["⚠️ G-PENDING-CHECK: 发现待处理的 update_brain 批次。", ""]

        if active_batches:
            lines.append("  活跃 pending 批次:")
            lines.extend(_format_batch_line(batch) for batch in active_batches[:5])
            if len(active_batches) > 5:
                lines.append(f"  ... +{len(active_batches) - 5} more active batches")

        if draft_only_batches:
            if active_batches:
                lines.append("")
            lines.append("  不合规目录（应移到 proposals/）:")
            lines.extend(_format_batch_line(batch) for batch in draft_only_batches[:5])
            if len(draft_only_batches) > 5:
                lines.append(
                    f"  ... +{len(draft_only_batches) - 5} more non-conforming batches"
                )

        lines.extend(
            [
                "",
                "请先处理 pending/<batch>/base，或将纯草稿目录移到 "
                f"{PROPOSALS_DIR}/ ，再执行构建。",
                f"操作规范: {UPDATE_BRAIN_SPEC}",
            ]
        )
        return CheckResult.warn("G-PENDING-CHECK", "\n".join(lines), "HIGH")

    except Exception as exc:
        return CheckResult.warn(
            "G-PENDING-CHECK",
            f"⚠️ G-PENDING-CHECK: pending batch 扫描失败: {exc}",
            "MEDIUM",
        )
