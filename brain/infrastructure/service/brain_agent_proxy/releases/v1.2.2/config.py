"""Configuration loading and management."""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class ClientConfig(BaseModel):
    """Client (agent) configuration - maps API key to agent info."""
    agent_name: str
    description: str = ""
    provider: str  # provider ID to use
    model: str  # model requested by client


class OAuthCredentials(BaseModel):
    """OAuth credentials."""
    auth_endpoint: str = "https://github.com/login/oauth/access_token"
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_at: Optional[int] = None
    scope: str = "read:user"


class APIKeyCredentials(BaseModel):
    """API Key credentials."""
    require_auth: bool = True
    api_base_url: str = "http://127.0.0.1:4141"
    api_key: str = ""
    api_key_env: str = ""
    header_name: str = "Authorization"
    auth_scheme: str = "Bearer"


class ProviderCredentials(BaseModel):
    """Provider credentials - either OAuth or API Key."""
    type: str  # oauth, api_key
    oauth: Optional[OAuthCredentials] = None
    api_key: Optional[APIKeyCredentials] = None


class ProviderConfig(BaseModel):
    """Provider configuration."""
    id: str
    type: str  # oauth, api_key
    name: str
    description: str = ""

    # Credentials
    credentials: Optional[ProviderCredentials] = None

    # Deprecated: old format support
    oauth_config: Optional[Dict[str, Any]] = None
    api_key_config: Optional[Dict[str, Any]] = None

    # Models
    models: List[str] = Field(default_factory=list)

    # Protocols
    protocols: List[str] = Field(default_factory=list)

    # Capabilities
    capabilities: List[str] = Field(default_factory=list)

    # Priority
    priority: int = 100

    # Enabled
    enabled: bool = True

    # API Base URL (for api_key type)
    api_base_url: str = ""

    # Copilot account type: individual | business | enterprise
    account_type: str = "individual"


class RoutingConfig(BaseModel):
    """Routing configuration."""
    default_strategy: str = "capability_match"
    model_strategy_map: Dict[str, str] = Field(default_factory=dict)
    fallback_enabled: bool = True
    cross_protocol_forbidden: bool = True
    max_depth: int = 3
    model_provider_map: Dict[str, str] = Field(default_factory=dict)
    api_key_provider_map: Dict[str, str] = Field(default_factory=dict)


class ProxyConfig(BaseModel):
    """Proxy configuration (new format)."""
    version: str = "1.0"
    clients: Dict[str, ClientConfig] = Field(default_factory=dict)
    model_routing: Dict[str, str] = Field(default_factory=dict)
    default_strategy: str = "capability_match"
    model_strategy_map: Dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Application configuration."""
    host: str = "0.0.0.0"
    port: int = 8210
    log_level: str = "INFO"

    providers: List[ProviderConfig] = Field(default_factory=list)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    proxy: Optional[ProxyConfig] = None

    @classmethod
    def load(cls, config_dir: Optional[Path] = None) -> "AppConfig":
        """Load configuration from files."""
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"

        # Load proxy.yaml (new format)
        proxy_config = None
        proxy_file = config_dir / "proxy.yaml"
        if proxy_file.exists():
            with open(proxy_file) as f:
                data = yaml.safe_load(f) or {}
                proxy_config = ProxyConfig(**data)

        # Load providers
        providers_file = config_dir / "providers.yaml"
        providers = []
        if providers_file.exists():
            with open(providers_file) as f:
                data = yaml.safe_load(f) or {}
                providers_data = data.get("providers", [])

                # Handle dict format (new) or list format (legacy)
                if isinstance(providers_data, dict):
                    # New format: dict of providers
                    for provider_id, p in providers_data.items():
                        p = p or {}
                        p["id"] = provider_id
                        p = cls._resolve_env_vars(p)
                        p = cls._convert_provider_format(p)
                        providers.append(ProviderConfig(**p))
                elif isinstance(providers_data, list):
                    # Legacy format: list of providers
                    for p in providers_data:
                        p = cls._resolve_env_vars(p)
                        p = cls._convert_provider_format(p)
                        providers.append(ProviderConfig(**p))

        # Load routing (routing.yaml)
        routing_file = config_dir / "routing.yaml"
        routing = RoutingConfig()
        if routing_file.exists():
            with open(routing_file) as f:
                data = yaml.safe_load(f) or {}
                routing = RoutingConfig(**data)

        # Merge proxy config into routing if present
        if proxy_config:
            # Use proxy's model_routing as model_provider_map
            if proxy_config.model_routing:
                routing.model_provider_map = proxy_config.model_routing
            if proxy_config.model_strategy_map:
                routing.model_strategy_map = proxy_config.model_strategy_map
            if proxy_config.default_strategy:
                routing.default_strategy = proxy_config.default_strategy

        return cls(providers=providers, routing=routing, proxy=proxy_config)

    @staticmethod
    def _resolve_env_vars(data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve environment variables in config."""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                    env_var = value[2:-1]
                    result[key] = os.environ.get(env_var, "")
                elif isinstance(value, dict):
                    result[key] = AppConfig._resolve_env_vars(value)
                else:
                    result[key] = value
            return result
        return data

    @staticmethod
    def _convert_provider_format(p: Dict[str, Any]) -> Dict[str, Any]:
        """Convert provider config to internal format."""
        # Convert to new format if needed
        if "oauth" in p and isinstance(p.get("oauth"), dict):
            # New format
            oauth_data = p.pop("oauth")
            p["credentials"] = ProviderCredentials(
                type="oauth",
                oauth=OAuthCredentials(**oauth_data)
            )
        elif "oauth_config" in p and p.get("type") in ("oauth", "oauth_device_legacy"):
            # Old format - convert
            old = p.pop("oauth_config")
            p["credentials"] = ProviderCredentials(
                type="oauth",
                oauth=OAuthCredentials(
                    auth_endpoint=old.get("token_url", "https://github.com/login/oauth/access_token"),
                    scope=old.get("scope", "read:user")
                )
            )

        if "api_key" in p and isinstance(p.get("api_key"), dict):
            # New format
            api_key_data = p.pop("api_key")
            if "credentials" not in p:
                p["credentials"] = ProviderCredentials(
                    type="api_key",
                    api_key=APIKeyCredentials(**api_key_data)
                )
            else:
                p["credentials"].api_key = APIKeyCredentials(**api_key_data)

        return p


# Global config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get global configuration."""
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config


def reload_config() -> AppConfig:
    """Reload configuration."""
    global _config
    _config = AppConfig.load()
    return _config
