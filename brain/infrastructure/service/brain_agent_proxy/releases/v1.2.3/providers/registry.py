"""Provider registry."""
from typing import Dict, List, Optional

from ..config import AppConfig, ProviderConfig
from .base import BaseProvider
from .oauth_device import OAuthDeviceProvider
from .api_key import APIKeyProvider


class ProviderRegistry:
    """Registry for providers."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._providers: Dict[str, BaseProvider] = {}
        self._init_providers()

    def _init_providers(self):
        """Initialize providers from config."""
        for provider_config in self.config.providers:
            if not provider_config.enabled:
                continue

            provider = self._create_provider(provider_config)
            if provider:
                self._providers[provider_config.id] = provider

    def _create_provider(self, config: ProviderConfig) -> Optional[BaseProvider]:
        """Create provider instance from config."""
        if config.type == "oauth_device" and config.oauth_config:
            return OAuthDeviceProvider(
                provider_id=config.id,
                token_file=config.oauth_config.token_file,
                auth_url=config.oauth_config.auth_url,
                token_url=config.oauth_config.token_url,
                scope=config.oauth_config.scope,
            )
        elif config.type == "api_key" and config.api_key_config:
            return APIKeyProvider(
                provider_id=config.id,
                api_base_url=config.api_key_config.api_base_url,
                env_var=config.api_key_config.env_var,
                header_name=config.api_key_config.header_name,
            )

        return None

    def get(self, provider_id: str) -> Optional[BaseProvider]:
        """Get provider by ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> List[BaseProvider]:
        """List all providers."""
        return list(self._providers.values())

    def find_by_model(self, model: str) -> Optional[BaseProvider]:
        """Find provider that supports the model."""
        for provider_config in self.config.providers:
            if provider_config.enabled and provider_config.supports_model(model):
                return self._providers.get(provider_config.id)
        return None
