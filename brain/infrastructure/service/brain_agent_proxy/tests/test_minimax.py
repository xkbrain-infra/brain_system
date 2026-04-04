import sys
import unittest
from pathlib import Path


CURRENT_DIR = Path("/xkagent_infra/brain/infrastructure/service/brain_agent_proxy/current")
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from providers.minimax import MiniMaxProvider


class MiniMaxProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = MiniMaxProvider(require_auth=False)

    def test_derives_multimodal_root_url_from_anthropic_base(self) -> None:
        provider = MiniMaxProvider(require_auth=False, api_base_url="https://api.minimaxi.com/anthropic")
        self.assertEqual(provider.get_api_root_url(), "https://api.minimaxi.com")

    def test_preserves_full_assistant_content_blocks(self) -> None:
        original = {
            "model": "minimax-m2.7",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "solve it"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "reason"},
                        {"type": "text", "text": "call tool"},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "lookup",
                            "input": {"q": "x"},
                        },
                    ],
                },
            ],
            "tools": [{"name": "lookup", "description": "search", "input_schema": {"type": "object"}}],
            "thinking": {"type": "enabled", "budget_tokens": 1024},
        }

        payload = self.provider.build_messages_payload(original, "MiniMax-M2.7")

        self.assertEqual(payload["messages"][1]["content"], original["messages"][1]["content"])
        self.assertEqual(payload["thinking"], original["thinking"])

    def test_strips_documented_ignored_fields(self) -> None:
        original = {
            "model": "minimax-m2.7",
            "messages": [{"role": "user", "content": "hi"}],
            "top_k": 10,
            "stop_sequences": ["END"],
            "service_tier": "priority",
            "mcp_servers": [{"name": "x"}],
            "context_management": {"mode": "auto"},
            "container": {"name": "sandbox"},
        }

        payload = self.provider.build_messages_payload(original, "MiniMax-M2.7")

        for field in ("top_k", "stop_sequences", "service_tier", "mcp_servers", "context_management", "container"):
            self.assertNotIn(field, payload)

    def test_rejects_unsupported_content_blocks(self) -> None:
        original = {
            "model": "minimax-m2.7",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
                        }
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "does not support content block type 'image'"):
            self.provider.build_messages_payload(original, "MiniMax-M2.7")

    def test_validates_temperature_range(self) -> None:
        original = {
            "model": "minimax-m2.7",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0,
        }

        with self.assertRaisesRegex(ValueError, r"range \(0\.0, 1\.0\]"):
            self.provider.build_messages_payload(original, "MiniMax-M2.7")

        original["temperature"] = 1.0
        payload = self.provider.build_messages_payload(original, "MiniMax-M2.7")
        self.assertEqual(payload["temperature"], 1.0)


if __name__ == "__main__":
    unittest.main()
