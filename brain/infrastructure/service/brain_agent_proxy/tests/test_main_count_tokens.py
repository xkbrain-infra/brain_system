"""Tests for main module compatibility helpers."""
import unittest

from src.main import _estimate_input_tokens_from_messages, _parse_json_response


class TestCountTokensEstimate(unittest.TestCase):
    def test_estimate_tokens_for_basic_messages(self):
        body = {
            "model": "gpt-5-mini",
            "messages": [
                {"role": "user", "content": "hello world"},
                {"role": "assistant", "content": "ok"},
            ],
        }

        tokens = _estimate_input_tokens_from_messages(body)
        self.assertGreater(tokens, 0)

    def test_estimate_tokens_with_structured_content(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "tool_result", "content": "second"},
                    ],
                }
            ],
            "system": "sys",
        }

        tokens = _estimate_input_tokens_from_messages(body)
        self.assertGreaterEqual(tokens, 1)


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self):
        import json
        return json.loads(self.text)


class TestJsonParseGuard(unittest.TestCase):
    def test_parse_json_response_ok(self):
        resp = FakeResponse(200, '{"ok": true}')
        data = _parse_json_response(resp)
        self.assertEqual(data["ok"], True)

    def test_parse_json_response_non_json_raises_readable_error(self):
        resp = FakeResponse(200, "")
        with self.assertRaises(ValueError) as ctx:
            _parse_json_response(resp)
        self.assertIn("non-JSON response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
