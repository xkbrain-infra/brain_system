import sys
import unittest
from pathlib import Path
from unittest.mock import patch


CURRENT_DIR = Path("/xkagent_infra/brain/infrastructure/service/brain_agent_proxy/current")
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from providers import claude_cli


class ClaudeCLIProviderTest(unittest.TestCase):
    def test_provider_defaults_to_default_permission_mode(self) -> None:
        provider = claude_cli.ClaudeCLIProvider()
        self.assertEqual(provider._permission_mode, "default")

    def test_provider_downgrades_bypass_permissions_for_root(self) -> None:
        with patch.object(claude_cli.os, "geteuid", return_value=0):
            provider = claude_cli.ClaudeCLIProvider(permission_mode="bypassPermissions")
        self.assertEqual(provider._permission_mode, "default")

    def test_build_cli_cmd_includes_default_add_dirs(self) -> None:
        provider = claude_cli.ClaudeCLIProvider()
        with patch.dict(claude_cli.os.environ, {"BRAIN_AGENT_PROXY_CLAUDE_DEFAULT_ADD_DIRS": "/root,/tmp"}, clear=False):
            cmd, _ = provider._build_cli_cmd("claude-sonnet-4-6", Path("/root"), include_partial_messages=False)
        joined = " ".join(cmd)
        self.assertIn("--add-dir /root", joined)

    def test_parse_stream_events_collects_retry_details(self) -> None:
        payload = "\n".join([
            '{"type":"system","subtype":"api_retry","error_status":500,"error":"server_error"}',
            '{"type":"result","result":"failed"}',
        ])
        parsed = claude_cli._parse_stream_events(payload)
        self.assertEqual(parsed["api_retries"], ["500 server_error"])
        self.assertEqual(parsed["result_event"]["result"], "failed")

    def test_format_cli_failure_prefers_retry_summary(self) -> None:
        parsed = {
            "api_retries": ["500 server_error", "500 server_error"],
            "raw_errors": [],
            "result_event": {},
        }
        detail = claude_cli._format_cli_failure(parsed, "", 1)
        self.assertIn("upstream retries failed", detail)
        self.assertIn("500 server_error", detail)

    def test_claude_auth_status_reports_not_logged_in(self) -> None:
        proc = type("Proc", (), {
            "stdout": '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}',
            "stderr": "",
            "returncode": 1,
        })()
        with patch.object(claude_cli.subprocess, "run", return_value=proc):
            ok, detail = claude_cli._claude_auth_status("claude")
        self.assertFalse(ok)
        self.assertIn("not authenticated", detail)


if __name__ == "__main__":
    unittest.main()
