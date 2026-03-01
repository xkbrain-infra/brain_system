from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

SERVICE_DIR = Path(__file__).resolve().parents[1]
import sys

if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config.loader import YAMLConfigLoader
from services.launcher import Launcher


def _write_registry(path: Path, desired_state: str = "running") -> None:
    data = {
        "groups": {
            "demo": [
                {
                    "name": "agent_demo_dev",
                    "tmux_session": "agent_demo_dev",
                    "cwd": "/brain/groups/org/demo/agents/agent_demo_dev",
                    "agent_type": "codex",
                    "required": False,
                    "desired_state": desired_state,
                    "status": "active",
                }
            ]
        }
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _build_launcher(config_dir: Path) -> Launcher:
    launcher = Launcher(self_name="service-agentctl")
    launcher._config_loader = YAMLConfigLoader(config_dir=config_dir)  # noqa: SLF001
    return launcher


class LauncherDesiredStateTests(unittest.TestCase):
    def test_set_desired_state_updates_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            registry = config_dir / "agents_registry.yaml"
            _write_registry(registry, desired_state="running")

            launcher = _build_launcher(config_dir)
            changed = launcher.set_desired_state("agent_demo_dev", "stopped")

            self.assertTrue(changed)
            updated = yaml.safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(updated["groups"]["demo"][0]["desired_state"], "stopped")

    def test_stop_with_persist_marks_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            registry = config_dir / "agents_registry.yaml"
            _write_registry(registry, desired_state="running")
            launcher = _build_launcher(config_dir)

            calls: list[list[str]] = []

            class _Proc:
                returncode = 0
                stderr = ""
                stdout = ""

            def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                calls.append(cmd)
                return _Proc()

            with mock.patch("services.launcher.subprocess.run", side_effect=_fake_run):
                launcher.stop("agent_demo_dev", reason="test", persist_desired_state=True)

            updated = yaml.safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(updated["groups"]["demo"][0]["desired_state"], "stopped")
            self.assertEqual(calls, [["tmux", "kill-session", "-t", "agent_demo_dev"]])


if __name__ == "__main__":
    unittest.main()
