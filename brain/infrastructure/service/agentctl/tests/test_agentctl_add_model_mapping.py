from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SERVICE_DIR = Path(__file__).resolve().parents[1]
AGENTCTL_BIN = SERVICE_DIR / "bin" / "agentctl"


class AgentCtlAddModelMappingTests(unittest.TestCase):
    def _run_add_dry_run(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        cmd = [
            str(AGENTCTL_BIN),
            "add",
            "agent-brain_frontdesk_test_dryrun",
            "--group",
            "brain",
            "--role",
            "frontdesk",
            "--agent-type",
            "copilot",
            *extra_args,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def test_default_model_uses_role_agent_model(self) -> None:
        result = self._run_add_dry_run()
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("model: Sonnet", result.stdout)

    def test_explicit_model_overrides_role_default(self) -> None:
        result = self._run_add_dry_run("--model", "gpt-5-mini")
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("model: gpt-5-mini", result.stdout)


if __name__ == "__main__":
    unittest.main()
