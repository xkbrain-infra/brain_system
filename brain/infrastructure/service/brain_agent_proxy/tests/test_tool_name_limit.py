import unittest

from src.main import _restore_tool_names_in_response, _rewrite_tool_names_for_provider


class _Provider:
    def __init__(self, pid: str):
        self.id = pid


class ToolNameLimitTests(unittest.TestCase):
    def test_rewrite_for_alibaba_truncates_tool_name_to_64(self):
        provider = _Provider("alibaba")
        long_name = "mcp__" + ("x" * 90)
        payload = {
            "model": "kimi-k2.5",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "name": long_name,
                    "description": "long tool",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }

        alias_map = _rewrite_tool_names_for_provider(payload, provider)

        rewritten = payload["tools"][0]["name"]
        self.assertLessEqual(len(rewritten), 64)
        self.assertIn(rewritten, alias_map)
        self.assertEqual(alias_map[rewritten], long_name)

    def test_restore_response_tool_name(self):
        original = "mcp__" + ("y" * 90)
        alias = "mcp__" + ("y" * 49) + "__0123456789"
        result = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"type": "function", "function": {"name": alias, "arguments": "{}"}}
                        ]
                    }
                }
            ]
        }

        _restore_tool_names_in_response(result, {alias: original})
        name = result["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
        self.assertEqual(name, original)


if __name__ == "__main__":
    unittest.main()
