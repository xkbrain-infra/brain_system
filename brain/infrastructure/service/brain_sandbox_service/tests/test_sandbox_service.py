from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/brain_sandbox_service/current/sandbox_service.py")
SPEC = importlib.util.spec_from_file_location("brain_sandbox_service_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SandboxManager = MODULE.SandboxManager


def test_write_sandbox_registry_upserts_without_dropping_existing_agents(tmp_path):
    manager = SandboxManager()
    config_dir = tmp_path / "config" / "agentctl"

    spec_one = {"name": "agent_brain_base_orchestrator_01", "role": "orchestrator"}
    spec_two = {"name": "agent_brain_base_dev_01", "role": "dev"}

    manager._write_sandbox_registry(config_dir, spec_one)
    manager._write_sandbox_registry(config_dir, spec_two)

    registry = yaml.safe_load((config_dir / "agents_registry.yaml").read_text(encoding="utf-8"))
    names = [entry["name"] for entry in registry["groups"]["brain"]]
    assert names == ["agent_brain_base_orchestrator_01", "agent_brain_base_dev_01"]


def test_resolve_instance_falls_back_to_runtime_state(tmp_path, monkeypatch):
    manager = SandboxManager()
    instance_id = "abc123"

    monkeypatch.setattr(manager.registry, "get", lambda _instance_id: None)
    monkeypatch.setattr(manager, "_sandbox_runtime_root", lambda _instance_id: tmp_path / _instance_id)

    record = {
        "instance_id": instance_id,
        "project": "base",
        "container_name": "brain-base-development-abc123",
        "status": "ready",
    }
    manager._write_runtime_instance_state(record)

    loaded = manager._resolve_instance(instance_id)
    assert loaded is not None
    assert loaded["container_name"] == "brain-base-development-abc123"


def test_prepare_runtime_state_removes_legacy_helper_code(tmp_path):
    manager = SandboxManager()
    runtime_root = tmp_path / "sandbox"
    state_root = runtime_root / ".bootstrap"
    state_root.mkdir(parents=True, exist_ok=True)
    helper = state_root / "ipc_socket_bridge.py"
    helper.write_text("print('legacy helper')\n", encoding="utf-8")
    state_file = state_root / "instance.yaml"
    state_file.write_text("instance_id: test\n", encoding="utf-8")

    manager._prepare_runtime_state(runtime_root)

    assert state_root.exists()
    assert not helper.exists()
    assert state_file.exists()
