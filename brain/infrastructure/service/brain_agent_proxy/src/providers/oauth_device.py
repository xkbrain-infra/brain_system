"""Generic OAuth Device provider (local proxy compatible)."""
import json
import os
import base64
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .base import BaseProvider


class OAuthDeviceProvider(BaseProvider):
    """Provider using OAuth Device token + configurable upstream base URL."""

    def __init__(
        self,
        provider_id: str,
        token_file: Optional[str] = None,
        auth_url: str = "https://github.com/login/device/code",
        token_url: str = "https://github.com/login/oauth/access_token",
        scope: str = "",
        api_base_url: str = "http://127.0.0.1:4141",
        require_auth: bool = False,
        header_name: str = "Authorization",
        auth_scheme: str = "Bearer",
        client_id: str = "",
        upstream_mode: str = "",
        codex_endpoint: str = "",
    ):
        self._provider_id = provider_id
        self._token_file = token_file or os.path.expanduser(
            f"~/.local/share/brain_agent_proxy/tokens/{provider_id}.json"
        )
        self._auth_url = auth_url
        self._token_url = token_url
        self._scope = scope
        self._api_base_url = api_base_url
        self._require_auth = require_auth
        self._header_name = header_name
        self._auth_scheme = auth_scheme
        self._client_id = client_id
        self._upstream_mode = (upstream_mode or "").strip().lower()
        self._codex_endpoint = codex_endpoint or "https://chatgpt.com/backend-api/codex/responses"
        self._cached_token: Optional[Dict[str, Any]] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "oauth_device"

    async def forward(self, request: Dict[str, Any], protocol: str = "chat_completions") -> Dict[str, Any]:
        """Forward request to upstream endpoint by protocol."""
        if self._provider_id == "openai" and self._upstream_mode == "chatgpt_codex":
            if protocol == "embeddings":
                raise ValueError("OpenAI ChatGPT OAuth path does not support embeddings")
            return await self._forward_openai_codex(request, protocol)

        endpoint = "/v1/chat/completions"
        if protocol == "messages":
            endpoint = "/v1/messages"
        elif protocol == "responses":
            endpoint = "/v1/responses"
        elif protocol == "embeddings":
            endpoint = "/v1/embeddings"

        headers = {"Content-Type": "application/json"}
        if protocol == "messages":
            headers["anthropic-version"] = "2023-06-01"
        if self._require_auth:
            token = await self.get_token()
            if not token:
                raise ValueError("No valid OAuth Device token available")
            if self._header_name.lower() == "authorization":
                scheme = (self._auth_scheme or "Bearer").strip()
                headers["Authorization"] = f"{scheme} {token}" if scheme else token
            else:
                headers[self._header_name] = token

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._api_base_url}{endpoint}", json=request, headers=headers)

        if resp.status_code != 200:
            raise ValueError(f"OAuth device upstream error: {resp.status_code} {resp.text}")

        return resp.json()

    async def forward_stream(self, request: Dict[str, Any], protocol: str = "chat_completions"):
        """Forward streaming request and yield raw bytes."""
        if self._provider_id == "openai" and self._upstream_mode == "chatgpt_codex":
            if protocol == "embeddings":
                raise ValueError("OpenAI ChatGPT OAuth path does not support embeddings")
            async for chunk in self._forward_openai_codex_stream(request, protocol):
                yield chunk
            return

        endpoint = "/v1/chat/completions"
        if protocol == "messages":
            endpoint = "/v1/messages"

        headers = {"Content-Type": "application/json"}
        if protocol == "messages":
            headers["anthropic-version"] = "2023-06-01"
        if self._require_auth:
            token = await self.get_token()
            if not token:
                raise ValueError("No valid OAuth Device token available")
            if self._header_name.lower() == "authorization":
                scheme = (self._auth_scheme or "Bearer").strip()
                headers["Authorization"] = f"{scheme} {token}" if scheme else token
            else:
                headers[self._header_name] = token

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self._api_base_url}{endpoint}", json=request, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"OAuth device upstream error: {resp.status_code} {body}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk

    async def health_check(self) -> bool:
        """Check if upstream proxy is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._api_base_url}/v1/models")
                return resp.status_code == 200
        except Exception:
            return False

    async def get_token(self) -> Optional[str]:
        """Get valid access token."""
        token_data = self._load_token()
        if not token_data:
            return None

        # Check if token is still valid
        expires_at = token_data.get("expires_at", 0)
        import time
        if expires_at > time.time():
            return token_data.get("access_token")

        # Try refresh
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            new_token = await self._refresh_token(refresh_token)
            if new_token:
                return new_token

        return None

    def _load_token(self) -> Optional[Dict[str, Any]]:
        """Load token from file."""
        token_file = Path(self._token_file).expanduser()
        if not token_file.exists():
            if self._provider_id == "openai":
                return self._load_from_codex_auth()
            # Only Copilot-compatible providers may reuse ~/.copilot/config.json.
            if "copilot" in self._provider_id:
                return self._load_from_copilot_config()
            return None

        try:
            with open(token_file) as f:
                return json.load(f)
        except Exception:
            return None

    def _load_from_codex_auth(self) -> Optional[Dict[str, Any]]:
        """Fallback to Codex local auth storage for OpenAI API key."""
        codex_auth = Path("~/.codex/auth.json").expanduser()
        if not codex_auth.exists():
            return None
        try:
            with open(codex_auth) as f:
                data = json.load(f)
            key = str(data.get("OPENAI_API_KEY", "")).strip()
            if not key or key.lower() == "none":
                return None
            return {
                "access_token": key,
                "token_type": "bearer",
                "expires_at": 9999999999,
            }
        except Exception:
            return None

    def _load_from_copilot_config(self) -> Optional[Dict[str, Any]]:
        """Load token from ~/.copilot/config.json."""
        copilot_config = Path("~/.copilot/config.json").expanduser()
        if not copilot_config.exists():
            return None

        try:
            import yaml
            with open(copilot_config) as f:
                config = yaml.safe_load(f)

            last_user = config.get("last_logged_in_user", {})
            host = last_user.get("host", "")
            login = last_user.get("login", "")
            if not host or not login:
                return None

            key = f"{host}:{login}"
            token = config.get("copilot_tokens", {}).get(key)
            if token:
                return {
                    "access_token": token,
                    "token_type": "bearer",
                    "expires_at": 9999999999,  # Long-lived
                }
        except Exception:
            pass

        return None

    async def _refresh_token(self, refresh_token: str) -> Optional[str]:
        """Refresh access token."""
        if not self._token_url:
            return None
        payload: Dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self._client_id:
            payload["client_id"] = self._client_id
        headers = {"Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self._token_url, data=payload, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
            access_token = str(data.get("access_token", "")).strip()
            if not access_token:
                return None
            expires_in = int(data.get("expires_in", 3600) or 3600)
            import time
            now = time.time()
            updated = {
                "access_token": access_token,
                "refresh_token": data.get("refresh_token", refresh_token),
                "token_type": data.get("token_type", "bearer"),
                "scope": data.get("scope", ""),
                "expires_at": int(now) + expires_in,
                "raw": data,
            }
            token_file = Path(self._token_file).expanduser()
            token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(token_file, "w") as f:
                json.dump(updated, f, indent=2)
            os.chmod(token_file, 0o600)
            return access_token
        except Exception:
            return None

    @staticmethod
    def _parse_jwt_claims(token: str) -> Optional[Dict[str, Any]]:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
            data = json.loads(decoded)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @classmethod
    def _extract_account_id_from_claims(cls, claims: Dict[str, Any]) -> Optional[str]:
        if not isinstance(claims, dict):
            return None
        aid = claims.get("chatgpt_account_id")
        if isinstance(aid, str) and aid:
            return aid
        auth_claim = claims.get("https://api.openai.com/auth")
        if isinstance(auth_claim, dict):
            aid = auth_claim.get("chatgpt_account_id")
            if isinstance(aid, str) and aid:
                return aid
        orgs = claims.get("organizations")
        if isinstance(orgs, list) and orgs:
            first = orgs[0]
            if isinstance(first, dict):
                oid = first.get("id")
                if isinstance(oid, str) and oid:
                    return oid
        return None

    def _extract_chatgpt_account_id(self, token_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(token_data, dict):
            return None
        raw = token_data.get("raw")
        if isinstance(raw, dict):
            id_token = raw.get("id_token")
            if isinstance(id_token, str) and id_token:
                claims = self._parse_jwt_claims(id_token)
                if claims:
                    aid = self._extract_account_id_from_claims(claims)
                    if aid:
                        return aid
        access_token = token_data.get("access_token")
        if isinstance(access_token, str) and access_token:
            claims = self._parse_jwt_claims(access_token)
            if claims:
                return self._extract_account_id_from_claims(claims)
        return None

    @staticmethod
    def _extract_text_from_responses(result: Dict[str, Any]) -> str:
        text = ""
        for item in result.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text += str(part.get("text", ""))
        return text

    @staticmethod
    def _normalize_tool_schema(schema: Any) -> Dict[str, Any]:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}

        out = dict(schema)
        if out.get("type") == "object" and "properties" not in out:
            out["properties"] = {}
        if out.get("type") is None and "properties" not in out:
            out["type"] = "object"
            out["properties"] = {}
        if not isinstance(out.get("properties"), dict):
            out["properties"] = {}

        required = out.get("required")
        if isinstance(required, list):
            normalized_required = []
            for item in required:
                if isinstance(item, str) and item:
                    normalized_required.append(item)
                elif isinstance(item, (list, tuple)):
                    for sub in item:
                        if isinstance(sub, str) and sub:
                            normalized_required.append(sub)
            # Deduplicate while preserving order.
            deduped = []
            seen = set()
            for name in normalized_required:
                if name in seen:
                    continue
                seen.add(name)
                deduped.append(name)
            out["required"] = deduped
        elif "required" in out:
            out["required"] = []

        return out

    @classmethod
    def _normalize_codex_tools(cls, raw_tools: Any) -> Optional[list[Dict[str, Any]]]:
        if not isinstance(raw_tools, list):
            return None

        tools: list[Dict[str, Any]] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue

            # chat-completions shape:
            # {"type":"function","function":{"name","description","parameters"}}
            fn = item.get("function")
            if isinstance(fn, dict):
                name = str(fn.get("name", "") or "").strip()
                if not name:
                    continue
                tools.append(
                    {
                        "type": "function",
                        "name": name,
                        "description": str(fn.get("description", "") or ""),
                        "parameters": cls._normalize_tool_schema(fn.get("parameters") or {}),
                    }
                )
                continue

            # anthropic messages shape:
            # {"name","description","input_schema"}
            name = str(item.get("name", "") or "").strip()
            if name:
                tools.append(
                    {
                        "type": "function",
                        "name": name,
                        "description": str(item.get("description", "") or ""),
                        "parameters": cls._normalize_tool_schema(item.get("input_schema") or {}),
                    }
                )
                continue

            # passthrough for already responses-compatible non-function tools
            tool_type = item.get("type")
            if isinstance(tool_type, str) and tool_type:
                tools.append(item)

        return tools if tools else None

    @staticmethod
    def _normalize_codex_tool_choice(tool_choice: Any) -> Any:
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice
        if not isinstance(tool_choice, dict):
            return None

        # chat-completions style: {"type":"function","function":{"name":"..."}}
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function")
            if isinstance(fn, dict):
                name = str(fn.get("name", "") or "").strip()
                if name:
                    return {"type": "function", "name": name}
            return "auto"

        # anthropic style: {"type":"tool","name":"..."}
        if tool_choice.get("type") == "tool":
            name = str(tool_choice.get("name", "") or "").strip()
            if name:
                return {"type": "function", "name": name}
            return "auto"

        return tool_choice

    @classmethod
    def _to_responses_input_content(cls, content: Any) -> list[Dict[str, Any]]:
        """Normalize mixed message content into OpenAI Responses input content items."""
        if isinstance(content, str):
            text = content
            return [{"type": "input_text", "text": text}] if text else []

        if isinstance(content, dict):
            ctype = str(content.get("type", "") or "")
            if ctype == "text":
                text = str(content.get("text", "") or "")
                return [{"type": "input_text", "text": text}] if text else []
            if ctype == "input_text":
                text = str(content.get("text", "") or "")
                return [{"type": "input_text", "text": text}] if text else []
            if ctype in {"image", "input_image"}:
                image_url = None
                if isinstance(content.get("image_url"), str):
                    image_url = content.get("image_url")
                source = content.get("source")
                if not image_url and isinstance(source, dict):
                    media_type = str(source.get("media_type", "") or "")
                    data = source.get("data")
                    if isinstance(data, str) and data:
                        if media_type:
                            image_url = f"data:{media_type};base64,{data}"
                        else:
                            image_url = f"data:image/png;base64,{data}"
                if image_url:
                    return [{"type": "input_image", "image_url": image_url}]
                return []
            # Fallback: stringify unknown block.
            return [{"type": "input_text", "text": json.dumps(content, ensure_ascii=False)}]

        if isinstance(content, list):
            out: list[Dict[str, Any]] = []
            for item in content:
                out.extend(cls._to_responses_input_content(item))
            return out

        return [{"type": "input_text", "text": str(content)}]

    @classmethod
    def _build_codex_payload(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        # Normalize chat-completions or anthropic-messages into responses-style payload.
        if "input" in request and isinstance(request.get("input"), list):
            payload = dict(request)
            payload.setdefault("instructions", "You are a coding assistant.")
            payload["store"] = False
            payload["stream"] = bool(request.get("stream", False))
            normalized_input: list[Dict[str, Any]] = []
            for item in payload.get("input", []) or []:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "user") or "user")
                normalized_input.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": cls._to_responses_input_content(item.get("content", "")),
                    }
                )
            payload["input"] = normalized_input
            normalized_tools = cls._normalize_codex_tools(payload.get("tools"))
            if normalized_tools is not None:
                payload["tools"] = normalized_tools
            normalized_tool_choice = cls._normalize_codex_tool_choice(payload.get("tool_choice"))
            if normalized_tool_choice is not None:
                payload["tool_choice"] = normalized_tool_choice
            return payload

        messages = request.get("messages", []) or []
        instructions_parts = []
        input_items = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")
            if role == "system":
                instructions_parts.append(str(content))
                continue
            input_items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": cls._to_responses_input_content(content),
                }
            )

        payload: Dict[str, Any] = {
            "model": request.get("model"),
            "input": input_items,
            "instructions": "\n".join(p for p in instructions_parts if p).strip() or "You are a coding assistant.",
            "stream": bool(request.get("stream", False)),
            "store": False,
        }
        if request.get("temperature") is not None:
            payload["temperature"] = request.get("temperature")
        normalized_tools = cls._normalize_codex_tools(request.get("tools"))
        if normalized_tools is not None:
            payload["tools"] = normalized_tools
        normalized_tool_choice = cls._normalize_codex_tool_choice(request.get("tool_choice"))
        if normalized_tool_choice is not None:
            payload["tool_choice"] = normalized_tool_choice
        return payload

    async def _forward_openai_codex(self, request: Dict[str, Any], protocol: str) -> Dict[str, Any]:
        token = await self.get_token()
        if not token:
            raise ValueError("No valid OAuth Device token available")
        token_data = self._load_token()
        payload = self._build_codex_payload(request)
        # chatgpt codex backend expects streaming mode.
        payload["stream"] = True

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        account_id = self._extract_chatgpt_account_id(token_data)
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        # Non-stream caller: consume SSE from upstream and aggregate into one result.
        text_parts: list[str] = []
        result_id = "resp_codex"
        result_model = str(payload.get("model", "") or "")
        usage: Dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", self._codex_endpoint, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"OAuth device upstream error: {resp.status_code} {body}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    event_type = str(obj.get("type", "") or "")
                    if event_type == "response.created":
                        response_obj = obj.get("response", {}) or {}
                        rid = response_obj.get("id")
                        rmodel = response_obj.get("model")
                        if isinstance(rid, str) and rid:
                            result_id = rid
                        if isinstance(rmodel, str) and rmodel:
                            result_model = rmodel
                        continue
                    if event_type == "response.output_text.delta":
                        delta = obj.get("delta")
                        if isinstance(delta, str) and delta:
                            text_parts.append(delta)
                        continue
                    if event_type == "response.completed":
                        response_obj = obj.get("response", {}) or {}
                        rid = response_obj.get("id")
                        rmodel = response_obj.get("model")
                        if isinstance(rid, str) and rid:
                            result_id = rid
                        if isinstance(rmodel, str) and rmodel:
                            result_model = rmodel
                        usage_obj = response_obj.get("usage", {}) or {}
                        if isinstance(usage_obj, dict):
                            usage = usage_obj
                        continue

        text = "".join(text_parts)
        result = {
            "id": result_id,
            "model": result_model or str(payload.get("model", "") or ""),
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": usage,
        }

        if protocol == "chat_completions":
            return {
                "id": result.get("id", "chatcmpl_codex"),
                "model": result.get("model", payload.get("model", "")),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        if protocol == "messages":
            return {
                "id": result.get("id", "msg_codex"),
                "model": result.get("model", payload.get("model", "")),
                "content": text,
                "stop_reason": "end_turn",
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        return {
            "id": result.get("id", "resp_codex"),
            "model": result.get("model", payload.get("model", "")),
            "content": text,
            "messages": [],
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    async def _forward_openai_codex_stream(self, request: Dict[str, Any], protocol: str):
        token = await self.get_token()
        if not token:
            raise ValueError("No valid OAuth Device token available")
        token_data = self._load_token()
        payload = self._build_codex_payload(request)
        payload["stream"] = True

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        account_id = self._extract_chatgpt_account_id(token_data)
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", self._codex_endpoint, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"OAuth device upstream error: {resp.status_code} {body}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk

    def get_api_base_url(self) -> str:
        """Get API base URL."""
        return self._api_base_url
