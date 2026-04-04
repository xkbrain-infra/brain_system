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
SandboxConfig = MODULE.SandboxConfig


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


def test_resolve_project_name_prefers_existing_normalized_directory(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    (projects_root / "brain-bs028-sandbox").mkdir(parents=True)
    monkeypatch.setattr(
        SandboxConfig,
        "projects_root",
        classmethod(lambda cls: projects_root),
    )

    assert SandboxConfig.resolve_project_name("brain-BS-028-sandbox") == "brain-bs028-sandbox"


def test_get_project_alias_strips_group_prefix_and_honors_alias_map(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    (projects_root / "brain-bs028-sandbox").mkdir(parents=True)
    monkeypatch.setattr(
        SandboxConfig,
        "projects_root",
        classmethod(lambda cls: projects_root),
    )

    assert SandboxConfig.get_project_alias("brain-bs028-sandbox") == "bs028-sandbox"
    assert SandboxConfig.get_project_alias("brain_agent_proxy") == "agent-proxy"


def test_create_fails_before_docker_when_project_root_missing(monkeypatch, tmp_path):
    manager = SandboxManager()
    monkeypatch.setattr(manager.config, "load_platform_config", lambda: {})
    monkeypatch.setattr(manager.config, "load_provider_config", lambda _provider="docker": {})
    monkeypatch.setattr(manager.config, "load_project_config", lambda _project: None)
    monkeypatch.setattr(manager.naming, "generate_instance_id", lambda: "abc123")
    monkeypatch.setattr(manager, "_project_host_root", lambda _project: tmp_path / "missing-project")
    monkeypatch.setattr(
        manager,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("docker should not run")),
    )

    try:
        manager.create("brain-BS-028-sandbox", with_agent="orchestrator")
    except RuntimeError as exc:
        assert "project root does not exist" in str(exc)
    else:
        raise AssertionError("expected missing project root failure")


def test_ipc_bridge_script_container_points_to_synced_service_bundle():
    assert (
        SandboxManager.IPC_BRIDGE_SCRIPT_CONTAINER
        == "/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service/current/ipc_socket_bridge.py"
    )


def test_load_role_profile_defaults_project_orchestrator_to_minimax(tmp_path, monkeypatch):
    workflow_root = tmp_path / "workflow"
    config_dir = workflow_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "provider_profiles.yaml").write_text(
        """
role_profile_map:
  project_orchestrator: coordinator
providers:
  profiles:
    coordinator:
      provider: anthropic
      model: claude-sonnet-4-6
  available:
    minimax:
      agent_type: minimax
""".strip(),
        encoding="utf-8",
    )

    manager = SandboxManager()
    monkeypatch.setattr(manager, "_resolve_orchestrator_workflow_root", lambda: workflow_root)

    profile = manager._load_role_profile("project_orchestrator")

    assert profile["provider"] == "minimax"
    assert profile["model"] == "minimax/minimax-m2.7"


def test_resolve_project_role_maps_auditor_to_project_auditor():
    manager = SandboxManager()

    identity_role, profile_role = manager._resolve_project_role("auditor")

    assert identity_role == "auditor"
    assert profile_role == "project_auditor"


def test_resolve_project_role_uses_workflow_alias_config(tmp_path, monkeypatch):
    workflow_root = tmp_path / "workflow"
    config_dir = workflow_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "provider_profiles.yaml").write_text(
        """
project_role_aliases:
  watchdog:
    identity_role: auditor
    profile_role: project_auditor
role_profile_map:
  project_auditor: auditor
providers:
  profiles:
    auditor:
      provider: anthropic
      model: claude-sonnet-4-6
  available:
    anthropic:
      agent_type: claude
""".strip(),
        encoding="utf-8",
    )

    manager = SandboxManager()
    monkeypatch.setattr(manager, "_resolve_orchestrator_workflow_root", lambda: workflow_root)

    identity_role, profile_role = manager._resolve_project_role("watchdog")

    assert identity_role == "auditor"
    assert profile_role == "project_auditor"


def test_create_defaults_with_agent_to_orchestrator(monkeypatch, tmp_path):
    manager = SandboxManager()
    project_root = tmp_path / "brain-bs028-sandbox"
    project_root.mkdir(parents=True)

    monkeypatch.setattr(manager.config, "load_platform_config", lambda: {})
    monkeypatch.setattr(manager.config, "load_provider_config", lambda _provider="docker": {})
    monkeypatch.setattr(manager.config, "load_project_config", lambda _project: None)
    monkeypatch.setattr(manager.naming, "generate_instance_id", lambda: "abc123")
    monkeypatch.setattr(manager, "_project_host_root", lambda _project: project_root)
    monkeypatch.setattr(manager, "_prepare_env_vars", lambda *args, **kwargs: {"HOST_PORTS": {}})
    monkeypatch.setattr(manager, "_generate_compose", lambda *args, **kwargs: str(tmp_path / "compose.yaml"))
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_write_runtime_instance_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager.registry, "register", lambda _record: None)
    monkeypatch.setattr(manager.registry, "update", lambda *_args, **_kwargs: None)

    captured = {}

    def fake_bootstrap(**kwargs):
        captured.update(kwargs)
        return {
            "name": "agent_brain_brain-bs028-sandbox_orchestrator_01",
            "role": "orchestrator",
            "model": "minimax/minimax-m2.7",
            "cwd": str(tmp_path / "agent"),
            "tmux_session": "sbx_abc123__agent",
        }

    monkeypatch.setattr(manager, "_bootstrap_attached_agent", fake_bootstrap)
    monkeypatch.setattr(manager, "_verify_create_contract", lambda **_kwargs: None)

    record = manager.create("brain-BS-028-sandbox")

    assert captured["with_agent"] == "orchestrator"
    assert record["agent"]["role"] == "orchestrator"


def test_start_sandbox_agent_host_passes_runtime_tmux_env(monkeypatch, tmp_path):
    manager = SandboxManager()
    config_dir = tmp_path / "config" / "agentctl"
    runtime_root = tmp_path / "runtime"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(manager, "_running_inside_sandbox_bundle", lambda: False)
    monkeypatch.setattr(manager, "_generate_agent_configs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_prepare_runtime_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_sync_runtime_to_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_sync_service_bundles_to_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_ensure_container_ipc_bridges", lambda *_args, **_kwargs: None)

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return None

    monkeypatch.setattr(manager, "_run", fake_run)

    spec = {
        "name": "agent_brain_demo_orchestrator_01",
        "sandbox_id": "abc123",
    }

    manager._start_sandbox_agent(
        config_dir=config_dir,
        runtime_root=runtime_root,
        container_name="brain-demo-development-abc123",
        agent_name="agent_brain_demo_orchestrator_01",
        agent_spec=spec,
    )

    env = captured["env"]
    assert env["AGENTCTL_DOCKER_CONTAINER"] == "brain-demo-development-abc123"
    assert env["AGENTCTL_CONFIG_DIR_HINT"] == str(config_dir)
    assert env["BRAIN_SANDBOX_ID"] == "abc123"
    assert env["TMUX_TMPDIR"] == "/xkagent_infra/runtime/sandbox/abc123/.tmux"


def test_sync_service_bundles_to_container_copies_base_bundle_and_init(monkeypatch):
    manager = SandboxManager()
    calls = []

    monkeypatch.setattr(manager, "_run", lambda cmd, **kwargs: calls.append(cmd))

    manager._sync_service_bundles_to_container("brain-demo-development-abc123")

    serialized = [" ".join(map(str, cmd)) for cmd in calls]
    assert any("/xkagent_infra/brain/infrastructure/service/utils/tmux/." in cmd and "/xkagent_infra/runtime/sandbox/_services/service/utils/tmux/" in cmd for cmd in serialized)
    assert any("/xkagent_infra/brain/base/." in cmd and "/xkagent_infra/runtime/sandbox/_services/base/" in cmd for cmd in serialized)
    assert any("/xkagent_infra/brain/INIT.yaml" in cmd and "/xkagent_infra/runtime/sandbox/_services/INIT.yaml" in cmd for cmd in serialized)


def test_copy_readable_tree_skips_unreadable_files(tmp_path, monkeypatch):
    manager = SandboxManager()
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    readable = source_root / "settings.json"
    blocked = source_root / ".credentials.json"
    nested_dir = source_root / "subdir"
    nested_dir.mkdir()
    nested_readable = nested_dir / "prefs.json"
    readable.write_text("{}", encoding="utf-8")
    blocked.write_text("secret", encoding="utf-8")
    nested_readable.write_text("{}", encoding="utf-8")

    real_access = MODULE.os.access

    def fake_access(path, mode):
        if Path(path) == blocked:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(MODULE.os, "access", fake_access)

    copied = manager._copy_readable_tree(source_root, dest_root)

    assert copied == 2
    assert (dest_root / "settings.json").exists()
    assert (dest_root / "subdir" / "prefs.json").exists()
    assert not (dest_root / ".credentials.json").exists()
