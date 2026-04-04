import importlib.util
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/utils/tmux/src/tmux_utils.py")
LOADER = SourceFileLoader("tmux_utils_module", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("tmux_utils_module", LOADER)
tmux_utils = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = tmux_utils
SPEC.loader.exec_module(tmux_utils)


class TmuxUtilsTransportTest(unittest.TestCase):
    def test_tmux_uses_docker_exec_for_container_targets(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.dict(
            tmux_utils.os.environ,
            {
                "BRAIN_TMUX_CONTAINER": "sandbox-demo",
                "TMUX_TMPDIR": "/xkagent_infra/runtime/sandbox/abc123/.tmux",
            },
            clear=False,
        ):
            with mock.patch.object(tmux_utils.subprocess, "run", side_effect=fake_run):
                tmux_utils._tmux("display-message", "-t", "%1", "-p", "#{pane_id}", check=False)

        self.assertEqual(
            captured["cmd"],
            [
                "docker",
                "exec",
                "-i",
                "-w",
                "/",
                "sandbox-demo",
                "env",
                "TMUX_TMPDIR=/xkagent_infra/runtime/sandbox/abc123/.tmux",
                "tmux",
                "display-message",
                "-t",
                "%1",
                "-p",
                "#{pane_id}",
            ],
        )
        self.assertNotIn("env", captured["kwargs"])

    def test_tmux_sets_tmux_env_for_host_socket(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.dict(
            tmux_utils.os.environ,
            {
                "TMUX_SOCKET": "/tmp/brain.sock",
            },
            clear=False,
        ):
            with mock.patch.object(tmux_utils.subprocess, "run", side_effect=fake_run):
                tmux_utils._tmux("list-sessions", check=False)

        self.assertEqual(captured["cmd"], ["tmux", "list-sessions"])
        env = captured["kwargs"]["env"]
        self.assertEqual(env["TMUX"], "/tmp/brain.sock,0,0")


if __name__ == "__main__":
    unittest.main()
