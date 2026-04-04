import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl")
LOADER = SourceFileLoader("agentctl_bin", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("agentctl_bin", LOADER)
agentctl = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = agentctl
SPEC.loader.exec_module(agentctl)


class AgentCtlTmuxTest(unittest.TestCase):
    def test_normalize_agent_type_maps_anthropic_to_claude(self) -> None:
        self.assertEqual(agentctl._normalize_agent_type("anthropic"), "claude")
        self.assertEqual(agentctl._normalize_agent_type("claude_code"), "claude")

    def test_normalize_model_name_maps_claude_aliases(self) -> None:
        self.assertEqual(
            agentctl._normalize_model_name("claude-sonnet-4-6", "claude"),
            "claude-sonnet-4.6",
        )
        self.assertEqual(
            agentctl._normalize_model_name("Sonnet", "anthropic"),
            "claude-sonnet-4.6",
        )

    def test_sandbox_tmux_session_name_prefixes_project_agents(self) -> None:
        self.assertEqual(
            agentctl._sandbox_tmux_session_name("agent-demo", "abc123"),
            "sbx_abc123__agent-demo",
        )
        self.assertEqual(
            agentctl._sandbox_tmux_session_name("sbx_abc123__agent-demo", "abc123"),
            "sbx_abc123__agent-demo",
        )

    def test_preferred_tmux_tmpdir_isolated_per_sandbox(self) -> None:
        with mock.patch.dict(
            agentctl.os.environ,
            {
                "AGENTCTL_DOCKER_CONTAINER": "sandbox-1",
                "BRAIN_SANDBOX_ID": "abc123",
            },
            clear=False,
        ):
            self.assertEqual(
                agentctl._preferred_tmux_tmpdir(),
                "/xkagent_infra/runtime/sandbox/abc123/.tmux",
            )

    def test_preferred_tmux_tmpdir_uses_user_home_for_non_root_host(self) -> None:
        with mock.patch.dict(
            agentctl.os.environ,
            {
                "AGENTCTL_DOCKER_CONTAINER": "",
                "BRAIN_SANDBOX_ID": "",
                "IS_SANDBOX": "",
                "AGENTCTL_CONFIG_DIR_HINT": "",
            },
            clear=False,
        ):
            with mock.patch.object(agentctl.os, "geteuid", return_value=1000):
                with mock.patch.object(agentctl.Path, "home", return_value=Path("/home/ubuntu")):
                    self.assertEqual(
                        agentctl._preferred_tmux_tmpdir(),
                        "/home/ubuntu/.tmux-sock",
                    )

    def test_main_accepts_config_dir_after_subcommand(self) -> None:
        captured: dict[str, object] = {}

        def fake_add(args):
            captured["config_dir"] = args.config_dir
            captured["name"] = args.name
            return 0

        argv = [
            "brain-agentctl",
            "add",
            "agent-demo",
            "--group",
            "brain",
            "--config-dir",
            "/tmp/agentctl",
        ]
        with mock.patch.object(agentctl.sys, "argv", argv):
            with mock.patch.object(agentctl, "cmd_add", side_effect=fake_add):
                rc = agentctl.main()

        self.assertEqual(rc, 0)
        self.assertEqual(captured["config_dir"], "/tmp/agentctl")
        self.assertEqual(captured["name"], "agent-demo")

    def test_main_accepts_config_dir_equals_form_after_subcommand(self) -> None:
        captured: dict[str, object] = {}

        def fake_list(args):
            captured["config_dir"] = args.config_dir
            return 0

        argv = [
            "brain-agentctl",
            "list",
            "--config-dir=/tmp/agentctl",
        ]
        with mock.patch.object(agentctl.sys, "argv", argv):
            with mock.patch.object(agentctl, "cmd_list", side_effect=fake_list):
                rc = agentctl.main()

        self.assertEqual(rc, 0)
        self.assertEqual(captured["config_dir"], "/tmp/agentctl")

    def test_tmux_tmpdir_candidates_include_sandbox_legacy_paths(self) -> None:
        with mock.patch.dict(agentctl.os.environ, {"AGENTCTL_DOCKER_CONTAINER": "sandbox-1"}, clear=False):
            candidates = agentctl._tmux_tmpdir_candidates()
        self.assertEqual(candidates, ["/tmp/sandbox_tmux", "/home/ubuntu/.tmux-sock", None])

    def test_tmux_tmpdir_candidates_prefer_runtime_isolated_dir(self) -> None:
        with mock.patch.dict(
            agentctl.os.environ,
            {"AGENTCTL_DOCKER_CONTAINER": "sandbox-1", "BRAIN_SANDBOX_ID": "abc123"},
            clear=False,
        ):
            candidates = agentctl._tmux_tmpdir_candidates()
        self.assertEqual(
            candidates,
            ["/xkagent_infra/runtime/sandbox/abc123/.tmux", "/tmp/sandbox_tmux", "/home/ubuntu/.tmux-sock", None],
        )

    def test_find_session_checks_multiple_tmux_dirs(self) -> None:
        calls: list[str | None] = []

        def fake_run_tmux(*args, **kwargs):
            tmux_tmpdir = kwargs.get("tmux_tmpdir")
            calls.append(tmux_tmpdir)
            rc = 0 if tmux_tmpdir is None else 1
            return subprocess.CompletedProcess(["tmux", *args], rc, "", "")

        with mock.patch.object(agentctl, "_tmux_tmpdir_candidates", return_value=["/tmp/sandbox_tmux", None]):
            with mock.patch.object(agentctl, "_run_tmux", side_effect=fake_run_tmux):
                found, tmux_tmpdir = agentctl._find_session_tmux_tmpdir("agent-demo")

        self.assertTrue(found)
        self.assertIsNone(tmux_tmpdir)
        self.assertEqual(calls, ["/tmp/sandbox_tmux", None])

    def test_list_sessions_unions_multiple_tmux_dirs(self) -> None:
        def fake_run_tmux(*args, **kwargs):
            tmux_tmpdir = kwargs.get("tmux_tmpdir")
            if tmux_tmpdir == "/tmp/sandbox_tmux":
                return subprocess.CompletedProcess(["tmux", *args], 0, "agent_a\n", "")
            if tmux_tmpdir is None:
                return subprocess.CompletedProcess(["tmux", *args], 0, "agent_b\n", "")
            return subprocess.CompletedProcess(["tmux", *args], 1, "", "missing")

        with mock.patch.object(agentctl, "_tmux_tmpdir_candidates", return_value=["/tmp/sandbox_tmux", None]):
            with mock.patch.object(agentctl, "_run_tmux", side_effect=fake_run_tmux):
                sessions = agentctl._list_sessions()

        self.assertEqual(sessions, {"agent_a", "agent_b"})

    def test_load_spec_prefers_runtime_manifest_command(self) -> None:
        with tempfile.TemporaryDirectory() as config_dir, tempfile.TemporaryDirectory() as agent_dir:
            runtime_dir = Path(agent_dir) / ".brain"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "agent_runtime.json").write_text(
                json.dumps(
                    {
                        "runtime": {
                            "command": "claude",
                            "args": ["--dangerously-skip-permissions", "--effort", "medium"],
                            "env": {
                                "BRAIN_SANDBOX_ID": "abc123",
                            },
                            "agent_type": "minimax",
                            "use_claude_cli": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            Path(config_dir, "agents_registry.yaml").write_text(
                "\n".join(
                    [
                        "groups:",
                        "  brain:",
                        "    - name: agent-demo",
                        "      tmux_session: sbx_abc123__agent-demo",
                        f"      cwd: {agent_dir}",
                        "      agent_type: minimax",
                        "      group: brain",
                        "      role: orchestrator",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = agentctl._load_spec(Path(config_dir))

        self.assertIn("agent-demo", loaded)
        self.assertEqual(
            loaded["agent-demo"].start_cmd,
            "IS_SANDBOX=1 claude --dangerously-skip-permissions",
        )

    def test_start_session_uses_fixed_command_for_claude_cli(self) -> None:
        with tempfile.TemporaryDirectory() as agent_dir:
            runtime_dir = Path(agent_dir) / ".brain"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "agent_runtime.json").write_text(
                json.dumps(
                    {
                        "runtime": {
                            "command": "claude",
                            "args": ["--dangerously-skip-permissions", "--effort", "medium"],
                            "env": {
                                "ANTHROPIC_BASE_URL": "http://host.docker.internal:8210",
                                "BRAIN_SANDBOX_ID": "abc123",
                            },
                            "agent_type": "minimax",
                            "use_claude_cli": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            spec = agentctl.AgentSpec(
                name="agent-demo",
                tmux_session="sbx_abc123__agent-demo",
                start_cmd="claude",
                cwd=agent_dir,
                status="active",
                agent_type="minimax",
                role="orchestrator",
                group="brain",
                description="",
                raw_spec={
                    "cli_type": "claude",
                    "env": {
                        "IS_SANDBOX": "1",
                        "BRAIN_SANDBOX_ID": "abc123",
                    },
                },
            )
            captured: dict[str, object] = {}

            def fake_tmux(*args, **kwargs):
                captured["args"] = args
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

            with mock.patch.object(agentctl, "_has_session", return_value=False):
                with mock.patch.object(agentctl, "_current_username", return_value="ubuntu"):
                    with mock.patch.object(agentctl, "_tmux", side_effect=fake_tmux):
                        agentctl._start_session(spec, apply=True, config_gen=False)

        shell_cmd = captured["args"][-1]
        self.assertEqual(shell_cmd, "IS_SANDBOX=1 claude --dangerously-skip-permissions")

    def test_start_session_defaults_to_current_user_for_host_claude_cli(self) -> None:
        with tempfile.TemporaryDirectory() as agent_dir:
            runtime_dir = Path(agent_dir) / ".brain"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "agent_runtime.json").write_text(
                json.dumps(
                    {
                        "runtime": {
                            "command": "claude",
                            "args": ["--dangerously-skip-permissions", "agent-demo"],
                            "env": {
                                "ANTHROPIC_BASE_URL": "http://127.0.0.1:8210",
                            },
                            "agent_type": "minimax",
                            "use_claude_cli": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            spec = agentctl.AgentSpec(
                name="agent-demo",
                tmux_session="agent-demo",
                start_cmd="claude",
                cwd=agent_dir,
                status="active",
                agent_type="minimax",
                role="devops",
                group="brain",
                description="",
                raw_spec={
                    "cli_type": "claude",
                    "env": {},
                },
            )
            captured: dict[str, object] = {}

            def fake_tmux(*args, **kwargs):
                captured["args"] = args
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

            with mock.patch.object(agentctl, "_has_session", return_value=False):
                with mock.patch.object(agentctl, "_tmux_context_is_sandbox", return_value=False):
                    with mock.patch.object(agentctl, "_current_username", return_value="root"):
                        with mock.patch.object(agentctl, "_tmux", side_effect=fake_tmux):
                            agentctl._start_session(spec, apply=True, config_gen=False)

        shell_cmd = captured["args"][-1]
        self.assertNotIn("sudo --preserve-env=", shell_cmd)
        self.assertEqual(shell_cmd, "IS_SANDBOX=1 claude --dangerously-skip-permissions")

    def test_start_session_honors_run_as_user_override(self) -> None:
        with tempfile.TemporaryDirectory() as agent_dir:
            runtime_dir = Path(agent_dir) / ".brain"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "agent_runtime.json").write_text(
                json.dumps(
                    {
                        "runtime": {
                            "command": "claude",
                            "args": ["--dangerously-skip-permissions", "agent-demo"],
                            "env": {
                                "ANTHROPIC_BASE_URL": "http://127.0.0.1:8210",
                            },
                            "agent_type": "minimax",
                            "use_claude_cli": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            spec = agentctl.AgentSpec(
                name="agent-demo",
                tmux_session="agent-demo",
                start_cmd="claude",
                cwd=agent_dir,
                status="active",
                agent_type="minimax",
                role="devops",
                group="brain",
                description="",
                raw_spec={
                    "cli_type": "claude",
                    "run_as_user": "ubuntu",
                    "env": {},
                },
            )
            captured: dict[str, object] = {}

            def fake_tmux(*args, **kwargs):
                captured["args"] = args
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

            with mock.patch.object(agentctl, "_has_session", return_value=False):
                with mock.patch.object(agentctl, "_tmux_context_is_sandbox", return_value=False):
                    with mock.patch.object(agentctl, "_current_username", return_value="root"):
                        with mock.patch.object(agentctl.os, "geteuid", return_value=0):
                            with mock.patch.object(agentctl, "_tmux", side_effect=fake_tmux):
                                agentctl._start_session(spec, apply=True, config_gen=False)

        shell_cmd = captured["args"][-1]
        self.assertEqual(
            shell_cmd,
            "exec sudo -H -u ubuntu bash -lc 'IS_SANDBOX=1 claude --dangerously-skip-permissions'",
        )

    def test_start_session_quotes_multiline_runtime_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as agent_dir:
            runtime_dir = Path(agent_dir) / ".brain"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "agent_runtime.json").write_text(
                json.dumps(
                    {
                        "runtime": {
                            "command": "claude",
                            "args": ["[Brain Skill Bindings]\nEnabled skills: lep, ipc."],
                            "env": {
                                "BRAIN_SANDBOX_ID": "abc123",
                            },
                            "agent_type": "minimax",
                            "use_claude_cli": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            spec = agentctl.AgentSpec(
                name="agent-demo",
                tmux_session="sbx_abc123__agent-demo",
                start_cmd="claude",
                cwd=agent_dir,
                status="active",
                agent_type="minimax",
                role="orchestrator",
                group="brain",
                description="",
                raw_spec={
                    "cli_type": "claude",
                    "env": {
                        "IS_SANDBOX": "1",
                        "BRAIN_SANDBOX_ID": "abc123",
                    },
                },
            )
            captured: dict[str, object] = {}

            def fake_tmux(*args, **kwargs):
                captured["args"] = args
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

            with mock.patch.object(agentctl, "_has_session", return_value=False):
                with mock.patch.object(agentctl, "_current_username", return_value="ubuntu"):
                    with mock.patch.object(agentctl, "_tmux", side_effect=fake_tmux):
                        agentctl._start_session(spec, apply=True, config_gen=False)

        shell_cmd = captured["args"][-1]
        self.assertEqual(shell_cmd, "IS_SANDBOX=1 claude --dangerously-skip-permissions")

    def test_run_tmux_uses_unified_tmux_api_for_container(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.dict(
            agentctl.os.environ,
            {
                "AGENTCTL_DOCKER_CONTAINER": "sandbox-1",
            },
            clear=False,
        ):
            with mock.patch.object(agentctl.subprocess, "run", side_effect=fake_run):
                agentctl._run_tmux("list-sessions", timeout_s=5.0, tmux_tmpdir="/tmp/sandbox_tmux")

        self.assertEqual(
            captured["cmd"],
            [agentctl._DEFAULT_TMUX_API_BIN, "raw", "--", "list-sessions"],
        )
        env = captured["kwargs"]["env"]
        self.assertEqual(env["BRAIN_TMUX_CONTAINER"], "sandbox-1")
        self.assertEqual(env["TMUX_TMPDIR"], "/tmp/sandbox_tmux")

    def test_resolve_tmux_api_bin_prefers_sandbox_bundle(self) -> None:
        with mock.patch.dict(
            agentctl.os.environ,
            {
                "AGENTCTL_DOCKER_CONTAINER": "sandbox-1",
                "BRAIN_SANDBOX_ID": "abc123",
            },
            clear=False,
        ):
            with mock.patch.object(agentctl.os.path, "exists", side_effect=lambda path: path == "/xkagent_infra/runtime/sandbox/_services/service/utils/tmux/bin/brain_tmux_api"):
                resolved = agentctl._resolve_tmux_api_bin()

        self.assertEqual(
            resolved,
            "/xkagent_infra/runtime/sandbox/_services/service/utils/tmux/bin/brain_tmux_api",
        )

    def test_cmd_add_infers_project_scope_from_sandbox_local_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "runtime" / "sandbox" / "abc123" / "config" / "agentctl"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "agents_registry.yaml").write_text(
                "\n".join(
                    [
                        "groups:",
                        "  brain:",
                        "    - name: agent_brain_demo_orchestrator_01",
                        "      tmux_session: sbx_abc123__agent_brain_demo_orchestrator_01",
                        f"      cwd: {config_dir.parent.parent / 'agents' / 'agent_brain_demo_orchestrator_01'}",
                        "      agent_type: minimax",
                        "      group: brain",
                        "      role: orchestrator",
                        "      scope: project",
                        "      project: demo-project",
                        "      sandbox_id: abc123",
                    ]
                ),
                encoding="utf-8",
            )
            args = agentctl.argparse.Namespace(
                config_dir=str(config_dir),
                name="agent_brain_dashboard_developer_01",
                group="brain",
                role="developer",
                agent_type="minimax",
                cli_type="",
                transport="proxy",
                model="minimax-m2.7",
                scope="group",
                project="",
                sandbox_id="",
                runtime_root="",
                path="",
                cwd="",
                desired_state="stopped",
                capabilities="",
                tags="",
                apply=False,
            )
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                rc = agentctl.cmd_add(args)

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("scope: project", output)
        self.assertIn("project: demo-project", output)
        self.assertIn("sandbox_id: abc123", output)
        self.assertIn("/runtime/sandbox/abc123/agents/agent_brain_dashboard_developer_01", output)

    def test_cmd_add_defaults_to_minimax_in_sandbox_local_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "runtime" / "sandbox" / "abc123" / "config" / "agentctl"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "agents_registry.yaml").write_text(
                "\n".join(
                    [
                        "groups:",
                        "  brain:",
                        "    - name: agent_brain_demo_orchestrator_01",
                        "      tmux_session: sbx_abc123__agent_brain_demo_orchestrator_01",
                        f"      cwd: {config_dir.parent.parent / 'agents' / 'agent_brain_demo_orchestrator_01'}",
                        "      agent_type: minimax",
                        "      group: brain",
                        "      role: orchestrator",
                        "      scope: project",
                        "      project: demo-project",
                        "      sandbox_id: abc123",
                    ]
                ),
                encoding="utf-8",
            )
            args = agentctl.argparse.Namespace(
                config_dir=str(config_dir),
                name="agent_brain_dashboard_researcher_01",
                group="brain",
                role="researcher",
                agent_type="claude",
                cli_type="",
                transport="proxy",
                model="",
                scope="group",
                project="",
                sandbox_id="",
                runtime_root="",
                path="",
                cwd="",
                desired_state="stopped",
                capabilities="",
                tags="",
                apply=False,
            )
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                rc = agentctl.cmd_add(args)

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("agent_type: minimax", output)
        self.assertIn("model: minimax-m2.7", output)

    def test_safe_agent_dir_rejects_project_root(self) -> None:
        self.assertFalse(
            agentctl._is_safe_agent_dir(
                "/xkagent_infra/groups/brain/projects/brain-dashboard-sandbox-binding",
                "agent_brain_dashboard_developer_01",
            )
        )
        self.assertTrue(
            agentctl._is_safe_agent_dir(
                "/xkagent_infra/runtime/sandbox/y5wl8j/agents/agent_brain_dashboard_developer_01",
                "agent_brain_dashboard_developer_01",
            )
        )


if __name__ == "__main__":
    unittest.main()
