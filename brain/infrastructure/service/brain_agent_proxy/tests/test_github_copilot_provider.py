import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers.github_copilot import GitHubCopilotProvider


class GitHubCopilotProviderTranslationTests(unittest.TestCase):
    def test_tool_results_are_emitted_before_followup_user_content(self):
        provider = GitHubCopilotProvider()
        payload = {
            "model": "gpt-5-mini",
            "messages": [
                {"role": "user", "content": "Call the tool"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running tool"},
                        {
                            "type": "tool_use",
                            "id": "call_123",
                            "name": "ipc_recv",
                            "input": {"ack_mode": "manual"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Thanks"},
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_123",
                            "content": [{"type": "text", "text": "{\"count\":1}"}],
                        },
                    ],
                },
            ],
        }

        translated = provider._translate_anthropic_to_openai(payload)
        messages = translated["messages"]

        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["tool_calls"][0]["id"], "call_123")
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[2]["tool_call_id"], "call_123")
        self.assertEqual(messages[3]["role"], "user")
        self.assertEqual(messages[3]["content"], "Thanks")

    def test_prefers_native_messages_for_gemini_family(self):
        provider = GitHubCopilotProvider()
        self.assertTrue(provider._prefers_native_messages("gemini-3.1-pro-preview"))
        self.assertTrue(provider._prefers_native_messages("claude-sonnet-4.6"))
        self.assertFalse(provider._prefers_native_messages("gpt-5-mini"))

    def test_dangling_tool_calls_are_stripped_before_submit(self):
        provider = GitHubCopilotProvider()
        payload = {
            "model": "gpt-5-mini",
            "messages": [
                {"role": "user", "content": "Call the tool"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running tool"},
                        {
                            "type": "tool_use",
                            "id": "call_123",
                            "name": "ipc_recv",
                            "input": {"ack_mode": "manual"},
                        },
                    ],
                },
                {"role": "user", "content": [{"type": "text", "text": "Actually never mind"}]},
            ],
        }

        translated = provider._translate_anthropic_to_openai(payload)
        messages = translated["messages"]

        self.assertEqual(messages[1]["role"], "assistant")
        self.assertNotIn("tool_calls", messages[1])
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[2]["content"], "Actually never mind")

    def test_dangling_anthropic_tool_use_is_stripped_for_native_messages(self):
        provider = GitHubCopilotProvider()
        payload = {
            "model": "gemini-3.1-pro-preview",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Run tool"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running tool"},
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "ipc_recv",
                            "input": {"ack_mode": "manual"},
                        },
                    ],
                },
                {"role": "user", "content": [{"type": "text", "text": "Never mind"}]},
            ],
        }

        sanitized = provider._sanitize_anthropic_messages_payload(payload)
        assistant_content = sanitized["messages"][1]["content"]

        self.assertEqual(assistant_content, [{"type": "text", "text": "Running tool"}])
        self.assertEqual(sanitized["messages"][2]["content"], [{"type": "text", "text": "Never mind"}])

    def test_openai_tool_payload_sanitizes_schema_and_name_length(self):
        provider = GitHubCopilotProvider()
        payload = {
            "model": "gpt-5-mini",
            "tools": [
                {
                    "name": "mcp__plugin_firebase_firebase__developerknowledge_search_documents",
                    "description": "Search docs",
                    "input_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                }
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }

        translated = provider._translate_anthropic_to_openai(payload)
        tool = translated["tools"][0]["function"]

        self.assertLessEqual(len(tool["name"]), 64)
        self.assertNotIn("$schema", tool["parameters"])
        self.assertIn("_tool_alias_map", translated)

    def test_save_and_cache_token_treats_refresh_in_as_relative_seconds(self):
        provider = GitHubCopilotProvider()
        with tempfile.TemporaryDirectory() as td:
            token_dir = Path(td)
            provider._token_dir = token_dir  # noqa: SLF001

            with patch("src.providers.github_copilot.time.time", return_value=1_700_000_000):
                asyncio.run(
                    provider._save_and_cache_token(  # noqa: SLF001
                        copilot_token="copilot-token",
                        expires_at=1_700_003_600,
                        refresh_in=1500,
                        github_token="ghu_test",
                    )
                )

            self.assertEqual(provider._token_refresh_at, 1_700_001_500)

    def test_get_valid_token_uses_saved_token_before_refresh_deadline(self):
        provider = GitHubCopilotProvider()
        with tempfile.TemporaryDirectory() as td:
            token_dir = Path(td)
            provider._token_dir = token_dir  # noqa: SLF001
            (token_dir / "copilot.json").write_text(
                '{"access_token":"saved-token","expires_at":1700003600,"refresh_in":1700001500,"github_token":"ghu_test"}'
            )

            with (
                patch("src.providers.github_copilot.time.time", return_value=1_700_000_000),
                patch.object(provider, "_get_copilot_token", side_effect=AssertionError("should not refresh")),
            ):
                token = asyncio.run(provider.get_valid_token())

            self.assertEqual(token, "saved-token")

    def test_get_valid_token_falls_back_to_saved_token_when_refresh_fails(self):
        provider = GitHubCopilotProvider()
        with tempfile.TemporaryDirectory() as td:
            token_dir = Path(td)
            provider._token_dir = token_dir  # noqa: SLF001
            (token_dir / "copilot.json").write_text(
                '{"access_token":"saved-token","expires_at":1700003600,"refresh_in":1699999000,"github_token":"ghu_test"}'
            )

            with (
                patch("src.providers.github_copilot.time.time", return_value=1_700_000_000),
                patch.object(provider, "_get_github_token_candidates", return_value=["ghu_test"]),
                patch.object(provider, "_get_copilot_token", return_value=None),
            ):
                token = asyncio.run(provider.get_valid_token())

            self.assertEqual(token, "saved-token")
            self.assertGreaterEqual(provider._token_refresh_at, 1_700_000_000)


if __name__ == "__main__":
    unittest.main()
