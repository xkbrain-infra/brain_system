"""Provider base classes."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseProvider(ABC):
    """Base class for providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Provider ID."""
        pass

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider type."""
        pass

    @abstractmethod
    async def forward(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Forward request to provider."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        pass

    def get_api_key(self) -> Optional[str]:
        """Get API key for provider."""
        return None

    def get_api_base_url(self) -> str:
        """Get API base URL."""
        return ""
