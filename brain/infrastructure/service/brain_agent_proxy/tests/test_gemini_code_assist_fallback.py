"""Tests for Gemini Code Assist error handling behavior."""
import unittest
from unittest.mock import patch

from src.providers.gemini import GeminiProvider


class _DummyResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _DummyAsyncClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _DummyResp(self._payload)


class TestGeminiCodeAssistFallback(unittest.IsolatedAsyncioTestCase):
    async def test_forward_propagates_code_assist_not_found(self):
        provider = GeminiProvider(use_code_assist_oauth=True)
        request = {"model": "gemini-3.1-pro-preview", "messages": [{"role": "user", "content": "hi"}]}

        with patch.object(provider, "_resolve_oauth_bearer", return_value="token"):
            with patch.object(
                provider,
                "_forward_code_assist_once",
                side_effect=ValueError('Gemini Code Assist error: 404 {"status":"NOT_FOUND"}'),
            ):
                with self.assertRaises(ValueError):
                    await provider.forward(request, protocol="messages")

    async def test_forward_uses_code_assist_result_when_available(self):
        provider = GeminiProvider(use_code_assist_oauth=True)
        request = {"model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "hi"}]}
        with patch.object(provider, "_resolve_oauth_bearer", return_value="token"):
            with patch.object(
                provider,
                "_forward_code_assist_once",
                return_value={
                    "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
                },
            ):
                out = await provider.forward(request, protocol="messages")

        self.assertEqual(out.get("model"), "gemini-2.5-pro")
        self.assertEqual(out.get("content", [{}])[0].get("type"), "text")


if __name__ == "__main__":
    unittest.main()
