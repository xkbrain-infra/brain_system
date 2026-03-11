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

    def test_format_error_falls_back_to_exception_type_when_message_empty(self):
        handler = MessagesProtocolHandler()
        resp = handler.format_error(Exception())
        self.assertEqual(resp["error"]["message"], "Exception()")


if __name__ == "__main__":
    unittest.main()
