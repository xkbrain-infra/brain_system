"""Tests for Anthropic messages protocol formatting."""
import unittest

from src.protocol.messages import MessagesProtocolHandler


class TestMessagesProtocolFormat(unittest.TestCase):
    def test_format_response_wraps_string_content_into_blocks(self):
        handler = MessagesProtocolHandler()
        resp = handler.format_response(
            {
                "id": "msg_1",
                "model": "gpt-5-mini",
                "content": "OK",
                "input_tokens": 1,
                "output_tokens": 1,
            }
        )

        self.assertIsInstance(resp["content"], list)
        self.assertEqual(resp["content"][0]["type"], "text")
        self.assertEqual(resp["content"][0]["text"], "OK")


if __name__ == "__main__":
    unittest.main()
