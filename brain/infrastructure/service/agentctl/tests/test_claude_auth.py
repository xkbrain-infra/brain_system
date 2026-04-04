import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/agentctl/services/claude_auth.py")
SPEC = importlib.util.spec_from_file_location("claude_auth", MODULE_PATH)
claude_auth = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(claude_auth)


class ClaudeAuthSpecTest(unittest.TestCase):
    def test_proxy_claude_requires_auth(self) -> None:
        spec = {
            "agent_type": "claude",
            "transport_mode": "proxy",
            "cli_type": "claude",
            "model": "claude-sonnet-4.6",
        }
        self.assertTrue(claude_auth.spec_requires_claude_auth(spec))

    def test_non_claude_proxy_does_not_require_claude_auth(self) -> None:
        spec = {
            "agent_type": "kimi",
            "transport_mode": "proxy",
            "cli_type": "claude",
            "model": "kimi-for-coding",
        }
        self.assertFalse(claude_auth.spec_requires_claude_auth(spec))

    def test_direct_claude_requires_auth(self) -> None:
        spec = {
            "agent_type": "claude",
            "transport_mode": "direct",
            "cli_type": "native",
            "model": "claude-sonnet-4.6",
        }
        self.assertTrue(claude_auth.spec_requires_claude_auth(spec))


if __name__ == "__main__":
    unittest.main()
