"""
BS-025-T3 单元测试：Config Loader
覆盖：合法配置解析、格式错误跳过、热更新检测
"""
import os
import sys
import time

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from config_loader import ConfigLoader, ProjectConfig


def _make_valid_yaml(tmp_path, project_id="BS-TEST", dirname="project-a"):
    """在 tmp_path/<dirname>/task_manager.yaml 写入合法 v2 配置。"""
    d = tmp_path / dirname
    d.mkdir(exist_ok=True)
    data = {
        "project_id": project_id,
        "runtime": {
            "check_interval": 30,
            "timeout_duration": 1800,
            "escalation_threshold": 2,
            "qa_agent": "agent_qa",
            "orchestrator_agent": "agent_orchestrator",
        },
        "agent_roster": [
            {"agent_name": "agent_dev", "role": "developer", "max_concurrent_tasks": 2}
        ],
        "tasks": [
            {"id": "T1", "title": "Task 1", "status": "pending", "priority": "high"}
        ],
    }
    p = d / "task_manager.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True))
    return str(p), data


# ── load_all ──────────────────────────────────────────────────────────────────

def test_load_all_valid_config(tmp_path):
    """合法 YAML 正确解析为 ProjectConfig。"""
    _make_valid_yaml(tmp_path, "BS-TEST")
    loader = ConfigLoader(str(tmp_path))
    configs = loader.load_all()

    assert len(configs) == 1
    cfg = configs[0]
    assert isinstance(cfg, ProjectConfig)
    assert cfg.project_id == "BS-TEST"
    assert cfg.check_interval == 30
    assert cfg.timeout_duration == 1800
    assert cfg.escalation_threshold == 2
    assert cfg.qa_agent == "agent_qa"
    assert cfg.orchestrator_agent == "agent_orchestrator"
    assert len(cfg.agent_roster) == 1
    assert cfg.agent_roster[0].agent_name == "agent_dev"
    assert cfg.agent_roster[0].max_concurrent_tasks == 2


def test_load_all_skips_invalid_yaml(tmp_path):
    """格式错误的 YAML 被跳过，不影响其他项目加载。"""
    _make_valid_yaml(tmp_path, "BS-OK", "ok-project")

    bad_dir = tmp_path / "bad-project"
    bad_dir.mkdir()
    (bad_dir / "task_manager.yaml").write_text(": invalid: [broken")

    loader = ConfigLoader(str(tmp_path))
    configs = loader.load_all()

    assert len(configs) == 1
    assert configs[0].project_id == "BS-OK"


def test_load_all_skips_missing_required_field(tmp_path):
    """缺少必填字段（如 runtime）的配置被跳过。"""
    d = tmp_path / "incomplete"
    d.mkdir()
    (d / "task_manager.yaml").write_text(
        yaml.dump({"project_id": "BS-INCOMPLETE", "agent_roster": [], "tasks": []})
    )
    loader = ConfigLoader(str(tmp_path))
    configs = loader.load_all()
    assert len(configs) == 0


def test_load_all_no_task_manager_yaml(tmp_path):
    """子目录无 task_manager.yaml 时跳过。"""
    (tmp_path / "empty-project").mkdir()
    loader = ConfigLoader(str(tmp_path))
    assert loader.load_all() == []


def test_load_all_nonexistent_dir(tmp_path):
    """projects_dir 不存在时返回空列表，不抛异常。"""
    loader = ConfigLoader(str(tmp_path / "nonexistent"))
    assert loader.load_all() == []


def test_load_all_multiple_projects(tmp_path):
    """多个合法项目全部加载。"""
    _make_valid_yaml(tmp_path, "BS-001", "proj1")
    _make_valid_yaml(tmp_path, "BS-002", "proj2")
    loader = ConfigLoader(str(tmp_path))
    configs = loader.load_all()
    assert len(configs) == 2
    ids = {c.project_id for c in configs}
    assert ids == {"BS-001", "BS-002"}


# ── hot reload ────────────────────────────────────────────────────────────────

def test_hot_reload_detects_mtime_change(tmp_path):
    """文件 mtime 变化时触发热更新，返回新内容。"""
    yaml_path, _ = _make_valid_yaml(tmp_path, "BS-HOT", "hot-project")
    loader = ConfigLoader(str(tmp_path))
    loader.load_all()

    # 修改文件内容，确保 mtime 变化（sleep 保证 mtime 不同）
    time.sleep(0.05)
    d = tmp_path / "hot-project"
    new_data = {
        "project_id": "BS-HOT-UPDATED",
        "runtime": {
            "check_interval": 60,
            "timeout_duration": 3600,
            "escalation_threshold": 3,
            "orchestrator_agent": "agent_orchestrator",
        },
        "agent_roster": [],
        "tasks": [],
    }
    (d / "task_manager.yaml").write_text(yaml.dump(new_data))

    updated = loader.check_hot_reload()
    assert len(updated) == 1
    assert updated[0].project_id == "BS-HOT-UPDATED"
    assert updated[0].check_interval == 60


def test_hot_reload_no_change(tmp_path):
    """mtime 未变化时，check_hot_reload 返回缓存中的原配置，不重新加载。"""
    _make_valid_yaml(tmp_path, "BS-STABLE", "stable-project")
    loader = ConfigLoader(str(tmp_path))
    loader.load_all()

    configs = loader.check_hot_reload()
    assert len(configs) == 1
    assert configs[0].project_id == "BS-STABLE"


# ── tasks format compatibility ────────────────────────────────────────────────

def test_tasks_dict_format_v1_compat(tmp_path):
    """兼容 v1 dict 格式的 tasks 字段。"""
    d = tmp_path / "v1-project"
    d.mkdir()
    data = {
        "project_id": "BS-V1",
        "runtime": {
            "check_interval": 60,
            "timeout_duration": 3600,
            "orchestrator_agent": "agent_orch",
        },
        "agent_roster": [],
        "tasks": {"T1": {"status": "done"}, "T2": {"status": "pending"}},
    }
    (d / "task_manager.yaml").write_text(yaml.dump(data))
    loader = ConfigLoader(str(tmp_path))
    configs = loader.load_all()
    assert len(configs) == 1
    assert len(configs[0].tasks) == 2
    ids = {t["id"] for t in configs[0].tasks}
    assert ids == {"T1", "T2"}
