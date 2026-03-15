"""API Key provider (OpenAI, Gemini, etc)."""
import os
from typing import Any, Dict, Optional

import httpx

from .base import BaseProvider


class APIKeyProvider(BaseProvider):
    """Provider using API Key authentication."""

    def __init__(
        self,
        provider_id: str,
        api_base_url: str,
        env_var: str,
        header_name: str = "Authorization",
    ):
        self._provider_id = provider_id
        self._api_base_url = api_base_url
        self._env_var = env_var
        self._header_name = header_name

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "api_key"

    async def forward(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Forward request to provider."""
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(f"No API key available for {self._provider_id}")

        url = f"{self._api_base_url}/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            self._header_name: f"Bearer {api_key}",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=request, headers=headers)

        if resp.status_code != 200:
            raise ValueError(f"API error: {resp.status_code} {resp.text}")

        return resp.json()

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        try:
            api_key = self.get_api_key()
            if not api_key:
                return False

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._api_base_url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                return resp.status_code == 200
        except Exception:
            return False

    def get_api_key(self) -> Optional[str]:
        """Get API key from environment."""
        return os.environ.get(self._env_var, "")

    def get_api_base_url(self) -> str:
        """Get API base URL."""
        return self._api_base_url
