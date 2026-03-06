"""Routing engine."""
import re
from typing import Any, Dict, Optional, Tuple

from ..config import AppConfig, ClientConfig, ProviderConfig
from .normalizer import NormalizedRequest
from .strategies import RoutingStrategy, CapabilityMatchStrategy, CostWeightedStrategy, AvailabilityStrategy


class RoutingEngine:
    """Routes requests to appropriate providers."""

    STRATEGIES = {
        "capability_match": CapabilityMatchStrategy,
        "cost_weighted": CostWeightedStrategy,
        "availability": AvailabilityStrategy,
    }

    def __init__(self, config: AppConfig):
        self.config = config
        self.strategies = {}

        # Initialize strategies
        for name, cls in self.STRATEGIES.items():
            self.strategies[name] = cls(config.providers)

    def find_provider(
        self,
        model: str,
        protocol: str,
    ) -> Optional[ProviderConfig]:
        """Find best provider for model and protocol."""
        provider_hint, model_name = self.parse_model_selector(model)
        effective_model = model_name or model
        hint_lc = provider_hint.lower() if provider_hint else ""

        # Check fixed mapping first
        provider_id = None
        if model in self.config.routing.model_provider_map:
            provider_id = self.config.routing.model_provider_map[model]
        elif effective_model in self.config.routing.model_provider_map:
            provider_id = self.config.routing.model_provider_map[effective_model]
        if provider_id:
            for p in self.config.providers:
                if p.id == provider_id and p.enabled:
                    if hint_lc and p.id.lower() != hint_lc and p.name.lower() != hint_lc:
                        continue
                    if self._matches_protocol(p, protocol):
                        return p

        # Find by model list
        matching_providers = [
            p for p in self.config.providers
            if p.enabled
            and effective_model in p.models
            and (not hint_lc or p.id.lower() == hint_lc or p.name.lower() == hint_lc)
            and self._matches_protocol(p, protocol)
        ]

        # If no direct match, try protocol fallback
        if not matching_providers and hasattr(self.config.routing, 'protocol_fallback'):
            fallback_protocol = self.config.routing.protocol_fallback.get(protocol)
            if fallback_protocol:
                matching_providers = [
                    p for p in self.config.providers
                    if p.enabled
                    and effective_model in p.models
                    and (not hint_lc or p.id.lower() == hint_lc or p.name.lower() == hint_lc)
                    and self._matches_protocol(p, fallback_protocol)
                ]
                # Override protocol for forwarding
                if matching_providers:
                    protocol = fallback_protocol

        if not matching_providers:
            return None

        # Apply routing strategy
        strategy_name = self.config.routing.model_strategy_map.get(
            effective_model,
            self.config.routing.default_strategy,
        )
        strategy = self.strategies.get(strategy_name, self.strategies["capability_match"])

        return strategy.select(matching_providers, effective_model)

    def _matches_protocol(self, provider: ProviderConfig, protocol: str) -> bool:
        """Check if provider supports the protocol."""
        # OAuth providers support all protocols via custom implementation
        if provider.type == "oauth":
            return True

        if provider.protocols:
            return protocol in provider.protocols

        # Legacy support
        if provider.type == "oauth_device":
            return True

        if protocol == "messages":
            return provider.cli_type == "messages"
        elif protocol == "chat_completions":
            return provider.cli_type in ("chat_completions", "messages")
        elif protocol == "responses":
            return provider.cli_type in ("responses", "chat_completions")
        return False

    def parse_client_key(self, api_key: str) -> Optional[Dict[str, str]]:
        """Parse supported client key formats.

        New canonical format:
            bgw-apx-v1--p-{provider}--m-{model}--n-{name}

        Legacy format:
            proxy-{provider}_{model}_{name}

        Args:
            api_key: e.g., bgw-apx-v1--p-minimax--m-minimax_m25--n-dev

        Returns:
            Dict with keys: provider, model, name, or None if invalid
        """
        # New format first.
        pattern_new = r"^bgw-apx-v1--p-([a-z0-9._-]+)--m-([a-z0-9._-]+)--n-([a-z0-9._-]+)$"
        match_new = re.match(pattern_new, api_key, re.IGNORECASE)
        if match_new:
            return {
                "provider": match_new.group(1),
                "model": match_new.group(2),
                "name": match_new.group(3),
            }

        # Match format: proxy-{provider}_{model}_{name}
        # Example: proxy-copilot_gpt5mini_dev
        pattern = r"^proxy-([a-z]+)_(.+)_([a-z0-9]+)$"
        match = re.match(pattern, api_key, re.IGNORECASE)
        if not match:
            return None

        return {
            "provider": match.group(1),  # e.g., "copilot"
            "model": match.group(2),     # e.g., "gpt5mini"
            "name": match.group(3),      # e.g., "dev"
        }

    def parse_model_selector(self, model: str) -> Tuple[Optional[str], str]:
        """Parse provider/model selector.

        Examples:
            minimax/MiniMax-M2.5 -> ("minimax", "MiniMax-M2.5")
            MiniMax-M2.5         -> (None, "MiniMax-M2.5")
        """
        raw = (model or "").strip()
        if "/" not in raw:
            return None, raw
        provider, _, rest = raw.partition("/")
        provider = provider.strip()
        model_name = rest.strip()
        if not provider or not model_name:
            return None, raw
        return provider, model_name

    def find_provider_by_client_key(self, api_key: str) -> Tuple[Optional[ProviderConfig], Optional[ClientConfig]]:
        """Find provider and client info by API key.

        Canonical format: bgw-apx-v1--p-{provider}--m-{model}--n-{name}
        Legacy format: proxy-{provider}_{model}_{name}

        Args:
            api_key: Client API key

        Returns:
            Tuple of (ProviderConfig, ClientConfig) or (None, None)
        """
        if not api_key:
            return None, None

        # Exact client-key match from proxy config should have highest priority.
        # This allows custom client ids that don't strictly match parse pattern.
        if self.config.proxy and self.config.proxy.clients:
            client = self.config.proxy.clients.get(api_key)
            if client:
                provider_id = client.provider
                for p in self.config.providers:
                    if p.id == provider_id and p.enabled:
                        return p, client

        # Try new format first
        parsed = self.parse_client_key(api_key)
        if parsed:
            # Fallback: try parsed provider
            provider_id = parsed["provider"]
            for p in self.config.providers:
                if p.id == provider_id and p.enabled:
                    return p, None

        # Fallback: old format (api_key_provider_map)
        provider = self.find_provider_by_api_key(api_key)
        if provider:
            return provider, None

        # Do not infer provider from unknown/ephemeral external keys.
        # Leave provider unresolved and let model-based routing decide.

        return None, None

    def find_provider_by_api_key(self, api_key: Optional[str]) -> Optional[ProviderConfig]:
        """Find provider by API key mapping (legacy format)."""
        if not api_key or not hasattr(self.config.routing, 'api_key_provider_map'):
            return None

        provider_id = self.config.routing.api_key_provider_map.get(api_key)
        if not provider_id:
            return None

        for p in self.config.providers:
            if p.id == provider_id and p.enabled:
                return p

        return None

    def _find_enabled_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """Find provider by id and ensure it's enabled."""
        for p in self.config.providers:
            if p.id == provider_id and p.enabled:
                return p
        return None

    def find_fallback(
        self,
        original_model: str,
        protocol: str,
        exclude_provider: str,
    ) -> Optional[ProviderConfig]:
        """Find fallback provider."""
        matching_providers = [
            p for p in self.config.providers
            if p.enabled
            and p.id != exclude_provider
            and self._matches_protocol(p, protocol)
        ]

        if not matching_providers:
            return None

        # Sort by priority
        matching_providers.sort(key=lambda p: p.priority)

        return matching_providers[0] if matching_providers else None
