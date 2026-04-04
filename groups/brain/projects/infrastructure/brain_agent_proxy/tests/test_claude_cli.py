import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


PROJECT_ROOT = Path("/xkagent_infra/groups/brain/projects/infrastructure/brain_agent_proxy")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.providers import claude_cli
from src import main as proxy_main
from src.providers import claude_cli as current_claude_cli


class _FakeStreamWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeTempFile:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.pos = 0
        self.closed = False

    def write(self, data: bytes) -> int:
        self.buffer.extend(data)
        self.pos = len(self.buffer)
        return len(data)

    def flush(self) -> None:
        return None

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = len(self.buffer) + offset
        return self.pos

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeStderr:
    async def read(self) -> bytes:
        return b""


class _FakeProcess:
    def __init__(self, stdout_lines: list[bytes]) -> None:
        self.stdin = _FakeStreamWriter()
        self.stdout = _FakeStdout(stdout_lines)
        self.stderr = _FakeStderr()

    async def wait(self) -> int:
        return 0


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

    def test_route_and_forward_stream_uses_claude_cli_stream_path(self) -> None:
        provider = SimpleNamespace(id="claude", type="claude_cli", claude_cli_config={})
        normalized = SimpleNamespace(
            model="claude-sonnet-4.6",
            original_request={"model": "claude-sonnet-4.6", "messages": []},
        )
        expected_stream = object()

        with patch.object(proxy_main, "_resolve_provider", return_value=(provider, None)):
            with patch.object(
                current_claude_cli.ClaudeCLIProvider,
                "forward_stream",
                new=AsyncMock(return_value=expected_stream),
            ) as forward_stream:
                result = asyncio.run(
                    proxy_main.route_and_forward_stream(
                        normalized,
                        "messages",
                        api_key="dummy",
                    )
                )

        self.assertIs(result, expected_stream)
        forward_stream.assert_awaited_once_with(normalized.original_request, "messages")

    def test_forward_stream_sends_prompt_via_stdin_not_argv(self) -> None:
        provider = claude_cli.ClaudeCLIProvider()
        prompt = "X" * 10000
        process = _FakeProcess(
            [
                b'{"type":"stream_event","event":{"type":"message_start","message":{"id":"msg_123","type":"message","role":"assistant","content":[]}}}\n',
                b"",
            ]
        )
        captured: dict[str, object] = {}
        prompt_file = _FakeTempFile()

        async def _fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return process

        async def _run() -> bytes:
            with patch.object(claude_cli, "_claude_auth_status", return_value=(True, "")):
                with patch.object(provider, "_build_prompt", return_value=prompt):
                    with patch.object(claude_cli.tempfile, "TemporaryFile", return_value=prompt_file):
                        with patch.object(claude_cli.asyncio, "create_subprocess_exec", new=_fake_create_subprocess_exec):
                            stream_iter = await provider.forward_stream(
                                {"model": "claude/claude-sonnet-4.6", "messages": [{"role": "user", "content": "hi"}]},
                                "messages",
                            )
                            return await anext(stream_iter)

        first_chunk = asyncio.run(_run())
        self.assertIn(b"message_start", first_chunk)
        self.assertEqual(prompt_file.buffer.decode("utf-8"), prompt)
        self.assertTrue(prompt_file.closed)
        self.assertNotIn(prompt, captured["args"])
        self.assertIs(captured["kwargs"]["stdin"], prompt_file)

    def test_forward_stream_synthesizes_sse_from_nonstream_assistant_error(self) -> None:
        provider = claude_cli.ClaudeCLIProvider()
        prompt_file = _FakeTempFile()
        process = _FakeProcess(
            [
                b"{\"type\":\"assistant\",\"message\":{\"id\":\"msg_rate\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"text\",\"text\":\"You've hit your limit\"}],\"stop_reason\":\"stop_sequence\",\"usage\":{\"input_tokens\":0,\"output_tokens\":0}}}\n",
                b"{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":true,\"result\":\"You've hit your limit\",\"stop_reason\":\"stop_sequence\",\"usage\":{\"input_tokens\":0,\"output_tokens\":0}}\n",
                b"",
            ]
        )

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return process

        async def _run() -> list[bytes]:
            with patch.object(claude_cli, "_claude_auth_status", return_value=(True, "")):
                with patch.object(claude_cli.tempfile, "TemporaryFile", return_value=prompt_file):
                    with patch.object(claude_cli.asyncio, "create_subprocess_exec", new=_fake_create_subprocess_exec):
                        stream_iter = await provider.forward_stream(
                            {"model": "claude/claude-sonnet-4.6", "messages": [{"role": "user", "content": "hi"}]},
                            "messages",
                        )
                        chunks = []
                        async for chunk in stream_iter:
                            chunks.append(chunk)
                        return chunks

        chunks = asyncio.run(_run())
        payload = b"".join(chunks).decode("utf-8")
        self.assertIn("message_start", payload)
        self.assertIn("You've hit your limit", payload)
        self.assertIn("message_stop", payload)


if __name__ == "__main__":
    unittest.main()
