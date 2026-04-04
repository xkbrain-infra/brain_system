from pathlib import Path

import yaml

import sys

PROJECT_ROOT = Path("/xkagent_infra/groups/brain/projects/infrastructure/brain_agent_proxy")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import AppConfig


def test_proxy_config_merges_sandbox_local_overlay(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "providers.yaml").write_text("providers: []\n", encoding="utf-8")
    (config_dir / "proxy.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "clients": {
                    "base-key": {
                        "agent_name": "agent-brain_manager",
                        "description": "base",
                        "provider": "minimax",
                        "model": "minimax-m2.7",
                    }
                },
                "model_routing": {"minimax/minimax-m2.7": "minimax"},
                "default_strategy": "capability_match",
                "model_strategy_map": {},
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    overlay_dir = tmp_path / "runtime" / "sandbox" / "abc123" / "config" / "agentctl"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "proxy.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "clients": {
                    "overlay-key": {
                        "agent_name": "agent_brain_base_designer_01",
                        "description": "overlay",
                        "provider": "minimax",
                        "model": "minimax-m2.7",
                    }
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "BRAIN_AGENT_PROXY_PROXY_OVERLAY_GLOB",
        str(tmp_path / "runtime" / "sandbox" / "*" / "config" / "agentctl" / "proxy.yaml"),
    )

    cfg = AppConfig.load(config_dir=config_dir)

    assert cfg.proxy is not None
    assert "base-key" in cfg.proxy.clients
    assert "overlay-key" in cfg.proxy.clients
    assert cfg.proxy.clients["overlay-key"].agent_name == "agent_brain_base_designer_01"
    assert cfg.routing.model_provider_map["minimax/minimax-m2.7"] == "minimax"
