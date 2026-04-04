import importlib.util
import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
