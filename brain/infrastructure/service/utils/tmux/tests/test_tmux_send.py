import importlib.util
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/utils/tmux/src/tmux_send.py")
LOADER = SourceFileLoader("tmux_send_module", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("tmux_send_module", LOADER)
tmux_send = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = tmux_send
SPEC.loader.exec_module(tmux_send)


class TmuxSendCliTest(unittest.TestCase):
    def test_missing_target_returns_error_instead_of_name_error(self) -> None:
        error = subprocess.CalledProcessError(
            127,
            ["tmux", "display-message"],
            stderr="can't find pane",
        )

        with mock.patch.object(tmux_send, "_ensure_target_exists", side_effect=error):
            rc = tmux_send.main(["-t", "%999", "hello"])

        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
