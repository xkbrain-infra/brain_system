"""
BS-025-T2 单元测试：State Store
覆盖：正常写入、crash 恢复、tmp 文件清理、RuntimeState 持久化
"""
import json
import os
import sys

import pytest
import yaml

# 将 staging/src 加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from state_store import (
    RuntimeState,
    cleanup_tmp_files,
    read_project_state,
    write_project_state,
)


# ── cleanup_tmp_files ─────────────────────────────────────────────────────────

def test_cleanup_tmp_files_removes_tmp(tmp_path):
    """启动时清理 *.yaml.tmp 残留文件。"""
    f1 = tmp_path / "a.yaml.tmp"
    f2 = tmp_path / "sub" / "b.yaml.tmp"
    f2.parent.mkdir()
    f1.write_text("leftover")
    f2.write_text("leftover")
    normal = tmp_path / "c.yaml"
    normal.write_text("keep")

    count = cleanup_tmp_files(str(tmp_path))

    assert count == 2
    assert not f1.exists()
    assert not f2.exists()
    assert normal.exists()


def test_cleanup_tmp_files_empty_dir(tmp_path):
    assert cleanup_tmp_files(str(tmp_path)) == 0


# ── read_project_state ────────────────────────────────────────────────────────

def test_read_project_state_ok(tmp_path):
    p = tmp_path / "task_manager.yaml"
    data = {"project_id": "BS-025", "tasks": []}
    p.write_text(yaml.dump(data))

    result = read_project_state(str(p))
    assert result == data


def test_read_project_state_not_found(tmp_path):
    result = read_project_state(str(tmp_path / "nonexistent.yaml"))
    assert result is None


def test_read_project_state_invalid_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(": invalid: yaml: [")
    result = read_project_state(str(p))
    assert result is None


# ── write_project_state ───────────────────────────────────────────────────────

def test_write_project_state_normal(tmp_path):
    """正常写入后内容正确，无 .tmp 残留。"""
    p = tmp_path / "state.yaml"
    data = {"project_id": "BS-025", "tasks": [{"id": "T1", "status": "done"}]}

    ok = write_project_state(str(p), data)

    assert ok is True
    assert p.exists()
    assert not (tmp_path / "state.yaml.tmp").exists()
    loaded = yaml.safe_load(p.read_text())
    assert loaded["project_id"] == "BS-025"
    assert loaded["tasks"][0]["status"] == "done"


def test_write_project_state_atomic_crash_simulation(tmp_path):
    """
    模拟写入中途 crash：.tmp 文件存在，旧 YAML 完整可读。
    通过在 .tmp 写入后、os.replace 前手动中断来模拟。
    """
    p = tmp_path / "state.yaml"
    old_data = {"project_id": "OLD", "tasks": []}
    p.write_text(yaml.dump(old_data))

    # 手动留下一个 .tmp（模拟 crash 残留）
    tmp_p = tmp_path / "state.yaml.tmp"
    tmp_p.write_text("incomplete data")

    # 旧 YAML 仍完整可读
    loaded = read_project_state(str(p))
    assert loaded["project_id"] == "OLD"

    # 再次正常写入应覆盖 .tmp 并完成 replace
    new_data = {"project_id": "NEW", "tasks": []}
    ok = write_project_state(str(p), new_data)
    assert ok is True
    loaded2 = read_project_state(str(p))
    assert loaded2["project_id"] == "NEW"
    assert not tmp_p.exists()


# ── RuntimeState ──────────────────────────────────────────────────────────────

def test_runtime_state_fresh_start(tmp_path):
    """文件不存在时从默认值启动。"""
    rs = RuntimeState(str(tmp_path / "runtime_state.json"))
    rs.load()
    assert len(rs.processed_msg_ids) == 0


def test_runtime_state_mark_and_save_reload(tmp_path):
    """mark_processed + save 后，重新 load 能恢复去重状态。"""
    json_path = str(tmp_path / "runtime_state.json")
    rs = RuntimeState(json_path)
    rs.load()

    rs.mark_processed("msg-001")
    rs.mark_processed("msg-002")
    rs.save()

    rs2 = RuntimeState(json_path)
    rs2.load()
    assert rs2.is_processed("msg-001")
    assert rs2.is_processed("msg-002")
    assert not rs2.is_processed("msg-003")


def test_runtime_state_idempotent_mark(tmp_path):
    """重复 mark 同一 msg_id 不会重复存储。"""
    rs = RuntimeState(str(tmp_path / "runtime_state.json"))
    rs.load()
    rs.mark_processed("dup")
    rs.mark_processed("dup")
    assert len(rs.processed_msg_ids) == 1


def test_runtime_state_invalid_json_resets(tmp_path):
    """JSON 损坏时重置到默认状态，不抛异常。"""
    p = tmp_path / "runtime_state.json"
    p.write_text("{invalid json")
    rs = RuntimeState(str(p))
    rs.load()
    assert len(rs.processed_msg_ids) == 0
