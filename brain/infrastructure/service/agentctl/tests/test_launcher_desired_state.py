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
from services.config_generator import generate_runtime_manifest


def _write_registry(path: Path, desired_state: str = "running") -> None:
    data = {
        "groups": {
            "demo": [
                {
                    "name": "agent_demo_dev",
                    "tmux_session": "agent_demo_dev",
                    "path": "/brain/groups/org/demo/agents/agent_demo_dev",
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

    def test_copilot_agent_defaults_to_claude_cli(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "agent-brain_frontdesk",
                    "agent_type": "copilot",
                    "cwd": td,
                    "model": "copilot/gpt-5-mini",
                    "cli_args": ["--dangerously-skip-permissions"],
                }
            )
            launcher = Launcher(self_name="service-agentctl")
            cmd = launcher._build_start_command(  # noqa: SLF001
                {
                    "name": "agent-brain_frontdesk",
                    "path": td,
                    "tmux_session": "agent-brain_frontdesk",
                }
            )

            self.assertEqual(cmd, "claude --model copilot/gpt-5-mini --dangerously-skip-permissions")

    def test_runtime_manifest_overrides_registry_launch_details(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "tmp-agent-gemini-cli",
                    "agent_type": "gemini",
                    "cli_type": "native",
                    "cwd": td,
                    "model": "gemini-2.5-pro",
                    "env": {"GEMINI_API_KEY": "${GEMINI_API_KEY}"},
                }
            )
            launcher = Launcher(self_name="service-agentctl")
            cmd = launcher._build_start_command(  # noqa: SLF001
                {
                    "name": "tmp-agent-gemini-cli",
                    "path": td,
                    "tmux_session": "tmp-agent-gemini-cli",
                }
            )

            self.assertEqual(cmd, "gemini --model gemini-2.5-pro")

    def test_restart_uses_path_as_cwd_for_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "agent_demo_dev",
                    "agent_type": "alibaba",
                    "cwd": td,
                    "model": "alibaba/kimi-k2.5",
                    "env": {"BRAIN_TRANSPORT_MODE": "proxy"},
                }
            )
            launcher = Launcher(self_name="service-agentctl")

            fake_spec = {
                "agent_demo_dev": {
                    "name": "agent_demo_dev",
                    "tmux_session": "agent_demo_dev",
                    "path": td,
                    "agent_type": "alibaba",
                }
            }

            calls: list[list[str]] = []

            class _Proc:
                returncode = 0
                stderr = ""
                stdout = ""

            def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                calls.append(cmd)
                return _Proc()

            with (
                mock.patch.object(launcher, "_get_agent_spec", return_value=fake_spec),
                mock.patch.object(launcher, "_setup_mcp_config"),
                mock.patch.object(launcher, "_setup_memory_capture"),
                mock.patch.object(launcher, "_should_restart", return_value=(True, "")),
                mock.patch.object(launcher, "_get_tmux_sessions", return_value=set()),
                mock.patch("services.launcher.subprocess.run", side_effect=_fake_run),
            ):
                result = launcher.restart("agent_demo_dev", reason="test")

            self.assertTrue(result.success)
            self.assertEqual(
                calls,
                [[
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    "agent_demo_dev",
                    "-c",
                    td,
                    "cd "
                    + td
                    + " && export TMUX_SESSION=agent_demo_dev && export TMUX_PANE=$(tmux display-message -p '#{pane_id}' 2>/dev/null) && BRAIN_TRANSPORT_MODE=proxy claude --model alibaba/kimi-k2.5",
                ]],
            )


if __name__ == "__main__":
    unittest.main()
