"""Tests for Gemini tool schema sanitization."""
import unittest

from src.providers.gemini import GeminiProvider


class TestGeminiToolsSchema(unittest.TestCase):
    def test_convert_tools_strips_dollar_prefixed_schema_keys(self):
        tools = [
            {
                "name": "search_docs",
                "description": "Search docs",
                "input_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "$id": "#query",
                        }
                    },
                    "$defs": {
                        "ignored": {"type": "string"}
                    },
                },
            }
        ]

        converted = GeminiProvider._convert_tools(tools)
        self.assertIsNotNone(converted)
        params = converted[0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("$schema", params)
        self.assertNotIn("$defs", params)
        self.assertEqual(params["properties"]["query"]["type"], "string")
        self.assertNotIn("$id", params["properties"]["query"])


if __name__ == "__main__":
    unittest.main()
