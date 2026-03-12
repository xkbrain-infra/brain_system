"""Unit tests for frontdesk outbound Telegram fallbacks."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import TelegramAPIService
from models import StandardMessage


def _build_service():
    service = TelegramAPIService.__new__(TelegramAPIService)
    service.bots = []
    service._recent_sources = {}
    return service


class TestFrontdeskOutbound(unittest.TestCase):
    def test_normalize_inbound_payload_from_json_string(self):
        service = _build_service()

        payload = service._normalize_inbound_payload(
            {
                "payload": {
                    "content": (
                        '{"type":"FRONTDESK_OUTBOUND","content":"hello",'
                        '"platform":"telegram","recent_source":true}'
                    )
                }
            }
        )

        self.assertEqual(payload["type"], "FRONTDESK_OUTBOUND")
        self.assertEqual(payload["content"], "hello")
        self.assertEqual(payload["platform"], "telegram")
        self.assertTrue(payload["recent_source"])

    def test_frontdesk_outbound_uses_recent_source_when_chat_missing(self):
        service = _build_service()
        bot = MagicMock()
        bot.name = "XKAgentBot"
        bot.client = MagicMock()
        service.bots = [bot]

        service._remember_recent_source(
            StandardMessage(
                platform="telegram",
                user_id="111",
                username="tester",
                chat_id="222",
                message_id="333",
                content_type="text",
                content="hello",
                attachments=[],
                timestamp="2026-03-11T00:00:00Z",
                source="XKAgentBot",
                metadata={},
            )
        )

        sent = asyncio.run(
            service._send_via_bot(
                {
                    "type": "FRONTDESK_OUTBOUND",
                    "content": "reply",
                    "recent_source": True,
                },
                "Sent message to",
            )
        )

        self.assertTrue(sent)
        bot.client.send_message.assert_called_once_with("222", "reply")

    def test_frontdesk_outbound_without_chat_id_or_recent_source_fails(self):
        service = _build_service()
        bot = MagicMock()
        bot.name = "XKAgentBot"
        bot.client = MagicMock()
        service.bots = [bot]

        sent = asyncio.run(
            service._process_inbound_message(
                {
                    "from": "agent-brain_frontdesk",
                    "msg_id": "abc123",
                    "payload": {
                        "content": '{"type":"FRONTDESK_OUTBOUND","content":"reply"}'
                    },
                }
            )
        )

        self.assertFalse(sent)
        bot.client.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
