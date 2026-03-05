"""Tests for routing engine key-based provider selection."""
import unittest

from src.config import AppConfig, ProviderConfig, RoutingConfig
from src.routing.engine import RoutingEngine


class TestRoutingEngineClientKeyFallback(unittest.TestCase):
    def test_exact_proxy_client_key_match_works_even_if_not_parseable(self):
        config = AppConfig(
            providers=[
                ProviderConfig(
                    id="gemini",
                    type="gemini",
                    name="Gemini",
                    enabled=True,
                    models=["gemini-2.5-pro"],
                    protocols=["messages", "chat_completions", "responses"],
                ),
            ],
            proxy={
                "version": "1.0",
                "clients": {
                    "proxy-gemini25pro_claude": {
                        "agent_name": "claude-gemini25pro",
                        "provider": "gemini",
                        "model": "gemini-2.5-pro",
                    }
                },
            },
            routing=RoutingConfig(),
        )
        engine = RoutingEngine(config)
        provider, client = engine.find_provider_by_client_key("proxy-gemini25pro_claude")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.id, "gemini")
        self.assertIsNotNone(client)
        self.assertEqual(client.agent_name, "claude-gemini25pro")

    def test_sk_ant_oat_key_falls_back_to_copilot_api_local(self):
        config = AppConfig(
            providers=[
                ProviderConfig(
                    id="copilot",
                    type="oauth",
                    name="Copilot OAuth",
                    enabled=True,
                    models=["gpt-5-mini"],
                    protocols=["messages"],
                ),
                ProviderConfig(
                    id="copilot-api-local",
                    type="api_key",
                    name="Copilot Local",
                    enabled=True,
                    models=["gpt-5-mini"],
                    protocols=["chat_completions"],
                ),
            ],
            routing=RoutingConfig(),
        )
        engine = RoutingEngine(config)

        provider, client = engine.find_provider_by_client_key(
            "sk-ant-oat01-HBRhRH13uFfDa6Bc96zSr84fKdGGTdw3dkXugQT"
        )

        self.assertIsNotNone(provider)
        self.assertEqual(provider.id, "copilot-api-local")
        self.assertIsNone(client)

    def test_unknown_non_proxy_key_returns_none_without_local_provider(self):
        config = AppConfig(
            providers=[
                ProviderConfig(
                    id="copilot",
                    type="oauth",
                    name="Copilot OAuth",
                    enabled=True,
                    models=["gpt-5-mini"],
                    protocols=["messages"],
                )
            ],
            routing=RoutingConfig(),
        )
        engine = RoutingEngine(config)

        provider, client = engine.find_provider_by_client_key("sk-ant-oat01-abc")

        self.assertIsNone(provider)
        self.assertIsNone(client)

    def test_parse_new_gateway_proxy_token_format(self):
        config = AppConfig(providers=[], routing=RoutingConfig())
        engine = RoutingEngine(config)
        parsed = engine.parse_client_key("bgw-apx-v1--p-minimax--m-minimax_m25--n-dev")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["provider"], "minimax")
        self.assertEqual(parsed["model"], "minimax_m25")
        self.assertEqual(parsed["name"], "dev")

    def test_provider_model_selector_prefers_provider_hint(self):
        config = AppConfig(
            providers=[
                ProviderConfig(
                    id="alibaba",
                    type="api_key",
                    name="Alibaba",
                    enabled=True,
                    models=["MiniMax-M2.5"],
                    protocols=["messages"],
                ),
                ProviderConfig(
                    id="minimax",
                    type="api_key",
                    name="MiniMax",
                    enabled=True,
                    models=["MiniMax-M2.5"],
                    protocols=["messages"],
                ),
            ],
            routing=RoutingConfig(),
        )
        engine = RoutingEngine(config)
        provider = engine.find_provider("minimax/MiniMax-M2.5", "messages")
        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider.id, "minimax")


if __name__ == "__main__":
    unittest.main()
