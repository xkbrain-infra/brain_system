#!/usr/bin/env python3
"""Tests for the batch-based pending checker override."""

import importlib.util
import sys
from pathlib import Path


HOOK_ROOT = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOK_ROOT / "lep"))

from result import CheckStatus, CheckContext  # noqa: E402


PENDING_CHECKER_PATH = (
    HOOK_ROOT / "overrides" / "agent-brain-manager" / "pending_checker.py"
)
spec = importlib.util.spec_from_file_location("pending_checker_override", PENDING_CHECKER_PATH)
pending_checker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(pending_checker)


def _context(tool_name: str = "deploy_publish") -> CheckContext:
    return CheckContext(
        gate_id="G-PENDING-CHECK",
        tool_name=tool_name,
        tool_input={},
        enforcement={"priority": "HIGH"},
        command=None,
        file_path=None,
    )


def test_pending_checker_passes_for_non_build_tool(tmp_path, monkeypatch):
    pending_root = tmp_path / "pending"
    pending_root.mkdir()
    monkeypatch.setattr(pending_checker, "PENDING_DIR", pending_root)
    monkeypatch.setattr(pending_checker, "PROPOSALS_DIR", tmp_path / "proposals")

    result = pending_checker.check(_context(tool_name="ls"))

    assert result.status == CheckStatus.PASS


def test_pending_checker_warns_for_active_batch(tmp_path, monkeypatch):
    pending_root = tmp_path / "pending"
    batch_root = pending_root / "20260314_test_batch"
    (batch_root / "base" / "spec").mkdir(parents=True)
    (batch_root / "base" / "spec" / "demo.yaml").write_text("ok: true\n", encoding="utf-8")
    (batch_root / "CHANGELOG.md").write_text("# demo\n", encoding="utf-8")

    monkeypatch.setattr(pending_checker, "PENDING_DIR", pending_root)
    monkeypatch.setattr(pending_checker, "PROPOSALS_DIR", tmp_path / "proposals")

    result = pending_checker.check(_context())

    assert result.status == CheckStatus.WARN
    assert "20260314_test_batch" in result.message
    assert "活跃 pending 批次" in result.message


def test_pending_checker_warns_for_draft_only_batch(tmp_path, monkeypatch):
    pending_root = tmp_path / "pending"
    batch_root = pending_root / "20260314_draft_only"
    batch_root.mkdir(parents=True)
    (batch_root / "DESIGN.md").write_text("# draft\n", encoding="utf-8")

    monkeypatch.setattr(pending_checker, "PENDING_DIR", pending_root)
    monkeypatch.setattr(pending_checker, "PROPOSALS_DIR", tmp_path / "proposals")

    result = pending_checker.check(_context())

    assert result.status == CheckStatus.WARN
    assert "不合规目录" in result.message
    assert "proposals" in result.message
