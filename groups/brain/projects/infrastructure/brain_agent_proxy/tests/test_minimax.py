import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


PROJECT_ROOT = Path("/xkagent_infra/groups/brain/projects/infrastructure/brain_agent_proxy")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import main as proxy_main
from src.providers.minimax import MiniMaxProvider


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

    def test_native_stream_retries_when_first_sse_has_no_visible_output(self) -> None:
        provider = SimpleNamespace(
            id="minimax",
            type="api_key",
            resolve_model=lambda raw: SimpleNamespace(
                upstream_name=lambda: raw.split("/", 1)[1] if "/" in raw else raw
            ),
        )
        normalized = SimpleNamespace(
            original_request={"messages": [{"role": "user", "content": "hi"}], "stream": True},
            model="minimax/minimax-m2.7",
        )

        empty_chunks = [
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_empty","type":"message","role":"assistant","content":[]}}\n\n',
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        text_chunks = [
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_ok","type":"message","role":"assistant","content":[]}}\n\n',
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}\n\n',
            b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        responses = [empty_chunks, text_chunks]
        stream_calls: list[dict] = []

        class _FakeResponse:
            def __init__(self, chunks):
                self.status_code = 200
                self._chunks = list(chunks)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_bytes(self):
                for chunk in self._chunks:
                    yield chunk

            async def aread(self):
                return b""

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json, headers):
                stream_calls.append({"method": method, "url": url, "json": json, "headers": headers})
                return _FakeResponse(responses.pop(0))

        async def _collect():
            chunks = []
            async for chunk in proxy_main._build_api_key_stream_iter(provider, normalized, "messages"):
                chunks.append(chunk)
            return chunks

        minimax_provider = SimpleNamespace(
            build_headers=lambda: {"x-api-key": "test"},
            build_messages_payload=lambda request, model: {"messages": request["messages"], "model": model},
            get_api_base_url=lambda: "https://example.invalid/anthropic",
        )

        with patch.object(proxy_main, "_minimax_chain", return_value="native"):
            with patch.object(proxy_main, "_build_minimax_provider", return_value=minimax_provider):
                with patch.object(proxy_main, "_rewrite_tool_names_for_provider", return_value={}):
                    with patch("httpx.AsyncClient", return_value=_FakeClient()):
                        with patch.object(proxy_main, "STREAM_MAX_RETRIES", 1):
                            with patch.object(proxy_main, "STREAM_RETRY_BASE_DELAY", 0):
                                with patch.object(proxy_main.asyncio, "sleep", new=AsyncMock(return_value=None)):
                                    chunks = asyncio.run(_collect())

        payload = b"".join(chunks)
        self.assertEqual(len(stream_calls), 2)
        self.assertIn(b"text_delta", payload)
        self.assertNotIn(b"msg_empty", payload)


if __name__ == "__main__":
    unittest.main()
