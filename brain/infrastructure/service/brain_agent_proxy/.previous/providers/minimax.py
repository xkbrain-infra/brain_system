"""Native MiniMax Anthropic-compatible provider helpers."""
import copy
import json
import os
from typing import Any, Dict, Optional

from .base import BaseProvider


_IGNORED_FIELDS = frozenset(
    {
        "top_k",
        "stop_sequences",
        "service_tier",
        "mcp_servers",
        "context_management",
        "container",
    }
)
_UNSUPPORTED_CONTENT_TYPES = frozenset({"image", "document"})


class MiniMaxProvider(BaseProvider):
    """MiniMax adapter for Anthropic-compatible /v1/messages."""

    def __init__(
        self,
        provider_id: str = "minimax",
        api_key: str = "",
        api_key_env: str = "MINIMAX_API_KEY",
        api_base_url: str = "https://api.minimaxi.com/anthropic",
        api_root_url: str = "",
        header_name: str = "x-api-key",
        auth_scheme: str = "",
        require_auth: bool = True,
        strip_ignored_fields: bool = True,
        validate_temperature: bool = True,
        reject_unsupported_content: bool = True,
    ):
        self._provider_id = provider_id
        self._api_key = (api_key or "").strip()
        self._api_key_env = api_key_env
        self._api_base_url = api_base_url.rstrip("/")
        self._api_root_url = (api_root_url or self._derive_api_root_url(api_base_url)).rstrip("/")
        self._header_name = header_name or "x-api-key"
        self._auth_scheme = (auth_scheme or "").strip()
        self._require_auth = bool(require_auth)
        self._strip_ignored_fields = bool(strip_ignored_fields)
        self._validate_temperature = bool(validate_temperature)
        self._reject_unsupported_content = bool(reject_unsupported_content)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "minimax"

    def get_api_key(self) -> Optional[str]:
        key = self._api_key or os.environ.get(self._api_key_env, "").strip()
        if key:
            return key
        try:
            token_path = os.path.expanduser(
                f"~/.local/share/brain_agent_proxy/tokens/{self._provider_id}_api_key.json"
            )
            if os.path.exists(token_path):
                with open(token_path) as f:
                    token_data = json.load(f) or {}
                token_key = str(token_data.get("api_key", "") or "").strip()
                if token_key:
                    return token_key
        except Exception:
            pass
        return ""

    def get_api_base_url(self) -> str:
        return self._api_base_url

    def get_api_root_url(self) -> str:
        return self._api_root_url

    @staticmethod
    def _derive_api_root_url(api_base_url: str) -> str:
        base = str(api_base_url or "").rstrip("/")
        if base.endswith("/anthropic"):
            return base[: -len("/anthropic")]
        if base.endswith("/anthropic/v1"):
            return base[: -len("/anthropic/v1")]
        return base

    def build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if not self._require_auth:
            return headers

        key = self.get_api_key()
        if not key:
            raise ValueError(
                f"Missing MiniMax API key: set {self._api_key_env} or "
                f"~/.local/share/brain_agent_proxy/tokens/{self._provider_id}_api_key.json"
            )

        if self._auth_scheme:
            headers[self._header_name] = f"{self._auth_scheme} {key}".strip()
        else:
            headers[self._header_name] = key
        return headers

    def build_messages_payload(self, original_request: Dict[str, Any], model: str) -> Dict[str, Any]:
        payload = copy.deepcopy(original_request or {})
        payload["model"] = model

        if self._strip_ignored_fields:
            for field in _IGNORED_FIELDS:
                payload.pop(field, None)

        if self._validate_temperature:
            self._validate_temperature_value(payload.get("temperature"))

        if self._reject_unsupported_content:
            self._validate_messages_content(payload.get("messages", []))

        return payload

    def _validate_temperature_value(self, temperature: Any) -> None:
        if temperature is None:
            return
        try:
            value = float(temperature)
        except (TypeError, ValueError) as exc:
            raise ValueError("MiniMax requires temperature to be numeric when provided") from exc
        if not (0.0 < value <= 1.0):
            raise ValueError("MiniMax requires temperature in range (0.0, 1.0]")

    def _validate_messages_content(self, messages: Any) -> None:
        if not isinstance(messages, list):
            return
        for message in messages:
            if isinstance(message, dict):
                self._validate_content_value(message.get("content"))

    def _validate_content_value(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self._validate_content_value(item)
            return
        if isinstance(value, dict):
            ctype = str(value.get("type", "") or "").strip().lower()
            if ctype in _UNSUPPORTED_CONTENT_TYPES:
                raise ValueError(f"MiniMax does not support content block type '{ctype}'")
            if "content" in value:
                self._validate_content_value(value.get("content"))

    async def forward(self, request: Dict[str, Any]) -> Dict[str, Any]:
        import httpx

        payload = self.build_messages_payload(request, str(request.get("model", "") or ""))
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._api_base_url}/v1/messages",
                json=payload,
                headers=self.build_headers(),
            )
        if resp.status_code != 200:
            raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")
        return resp.json()

    async def health_check(self) -> bool:
        return bool(self.get_api_key())
