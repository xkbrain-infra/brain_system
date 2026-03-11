import unittest

from src.providers.oauth_device import OAuthDeviceProvider


class OpenAICodexPayloadTests(unittest.TestCase):
    def test_assistant_messages_use_output_text_blocks(self) -> None:
        payload = OAuthDeviceProvider._build_codex_payload(
            {
                "model": "gpt-5.4",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                    {"role": "user", "content": "你是啥模型"},
                ],
            }
        )

        self.assertEqual(payload["input"][0]["content"][0]["type"], "input_text")
        self.assertEqual(payload["input"][1]["content"][0]["type"], "output_text")
        self.assertEqual(payload["input"][2]["content"][0]["type"], "input_text")

    def test_existing_text_blocks_are_normalized_by_role(self) -> None:
        payload = OAuthDeviceProvider._build_codex_payload(
            {
                "model": "gpt-5.4",
                "input": [
                    {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
                ],
            }
        )

        self.assertEqual(payload["input"][0]["content"][0]["type"], "output_text")
        self.assertEqual(payload["input"][0]["content"][0]["text"], "done")


if __name__ == "__main__":
    unittest.main()
