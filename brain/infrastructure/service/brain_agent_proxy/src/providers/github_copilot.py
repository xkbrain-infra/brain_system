"""GitHub Copilot Provider - 完全自研实现 (参考 copilot-api)."""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .base import BaseProvider
from ..config import get_config

# 来自 copilot-api 的常量
COPILOT_VERSION = "0.26.7"
EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
API_VERSION = "2025-04-01"
VSCODE_VERSION = "1.95.3"  # 任意版本即可


class GitHubCopilotProvider(BaseProvider):
    """
    GitHub Copilot Provider - 完全自研实现

    直接调用 GitHub Copilot API，参考 copilot-api 实现。
    """

    # GitHub API
    GITHUB_API_BASE = "https://api.github.com"
    COPILOT_TOKEN_URL = "/copilot_internal/v2/token"
    COPILOT_API_BASE = "https://api.githubcopilot.com"
    MODEL_ALIASES = {
        "gpt-5.1-mini": "gpt-5-mini",
    }
    MODEL_FALLBACK_PREFERENCE = [
        "gpt-5-mini",
        "gpt-41-copilot",
        "gpt-4o",
        "gpt-4o-mini",
    ]

    def __init__(
        self,
        provider_id: str = "copilot",
        token_dir: Optional[str] = None,
    ):
        self._provider_id = provider_id
        self._token_dir = Path(token_dir or os.path.expanduser(
            "~/.local/share/brain_agent_proxy/tokens"
        ))
        self._token_dir.mkdir(parents=True, exist_ok=True)
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._models_cache: list[str] = []
        self._models_cache_ts: float = 0.0

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "oauth_device"

    def _get_token_file(self) -> Path:
        return self._token_dir / f"{self._provider_id}.json"

    def _get_account_type(self) -> str:
        """Resolve Copilot account type for API base URL."""
        env_val = os.environ.get("COPILOT_ACCOUNT_TYPE", "").strip().lower()
        if env_val in ("individual", "business", "enterprise"):
            return env_val

        try:
            cfg = get_config()
            provider = next((p for p in cfg.providers if p.id == self._provider_id), None)
            if provider and provider.account_type in ("individual", "business", "enterprise"):
                return provider.account_type
        except Exception:
            pass
        return "individual"

    def _get_copilot_api_base(self) -> str:
        account_type = self._get_account_type()
        if account_type == "individual":
            return self.COPILOT_API_BASE
        return f"https://api.{account_type}.githubcopilot.com"

    def _get_github_token(self) -> Optional[str]:
        """Get GitHub token for Copilot token exchange.

        Priority:
        1) Explicit env var
        2) brain_agent_proxy token file (`github_token`)
        3) copilot-api token file
        4) ~/.copilot/config.json
        """
        # 1) Explicit env var
        env_token = os.environ.get("GITHUB_TOKEN", "").strip()
        if env_token:
            return env_token

        # 2) brain_agent_proxy token file
        saved = self._load_saved_token()
        if saved:
            token = (saved.get("github_token") or "").strip()
            if token:
                return token
        # 2.5) explicit github_oauth.json (written by auth helper)
        github_oauth_file = self._token_dir / "github_oauth.json"
        if github_oauth_file.exists():
            try:
                with open(github_oauth_file) as f:
                    data = json.load(f) or {}
                token = str(data.get("github_token", "") or "").strip()
                if token:
                    return token
            except Exception:
                pass

        # 3) copilot-api token file (legacy/shared)
        copilot_api_token = Path("~/.local/share/copilot-api/github_token").expanduser()
        if copilot_api_token.exists():
            try:
                token = copilot_api_token.read_text().strip()
                if token:
                    return token
            except Exception:
                pass

        # 4) ~/.copilot/config.json
        copilot_config = Path("~/.copilot/config.json").expanduser()
        if not copilot_config.exists():
            return None

        try:
            with open(copilot_config) as f:
                config = json.load(f)

            last_user = config.get("last_logged_in_user", {})
            host = last_user.get("host", "")
            login = last_user.get("login", "")
            if not host or not login:
                return None

            key = f"{host}:{login}"
            token = config.get("copilot_tokens", {}).get(key)
            return token
        except Exception:
            return None

    def _get_github_token_candidates(self) -> list[str]:
        """Collect candidate GitHub tokens in preferred order."""
        candidates: list[str] = []
        seen = set()

        def add(tok: Optional[str]):
            t = (tok or "").strip()
            if not t or t in seen:
                return
            seen.add(t)
            candidates.append(t)

        # 1) explicit env
        add(os.environ.get("GITHUB_TOKEN"))

        # 2) ~/.copilot/config.json (usually the most up-to-date interactive token)
        try:
            cfg = Path("~/.copilot/config.json").expanduser()
            if cfg.exists():
                with open(cfg) as f:
                    data = json.load(f)
                last_user = data.get("last_logged_in_user", {}) or {}
                host = last_user.get("host", "")
                login = last_user.get("login", "")
                if host and login:
                    add((data.get("copilot_tokens", {}) or {}).get(f"{host}:{login}"))
        except Exception:
            pass

        # 3) brain_agent_proxy token file
        try:
            saved = self._load_saved_token() or {}
            add(saved.get("github_token"))
        except Exception:
            pass

        # 3.5) dedicated github_oauth.json file
        try:
            p = self._token_dir / "github_oauth.json"
            if p.exists():
                with open(p) as f:
                    data = json.load(f) or {}
                add(data.get("github_token"))
        except Exception:
            pass

        # 4) shared copilot-api token file
        try:
            p = Path("~/.local/share/copilot-api/github_token").expanduser()
            if p.exists():
                add(p.read_text().strip())
        except Exception:
            pass

        return candidates

    def _load_saved_token(self) -> Optional[Dict[str, Any]]:
        # 先尝试通用的 copilot.json
        generic_file = self._token_dir / "copilot.json"
        if generic_file.exists():
            try:
                with open(generic_file) as f:
                    return json.load(f)
            except Exception:
                pass

        # 再尝试特定的文件名
        token_file = self._get_token_file()
        if not token_file.exists():
            return None

        try:
            with open(token_file) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_token(self, token_data: Dict[str, Any]):
        token_file = self._get_token_file()
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(token_file, 0o600)

    def _get_github_headers(self, github_token: str) -> Dict[str, str]:
        """Build headers for GitHub API calls (参考 copilot-api)."""
        return {
            "Authorization": f"token {github_token}",  # 注意是 "token" 不是 "Bearer"!
            "Accept": "application/json",
            "content-type": "application/json",
            "editor-version": f"vscode/{VSCODE_VERSION}",
            "editor-plugin-version": EDITOR_PLUGIN_VERSION,
            "user-agent": USER_AGENT,
            "x-github-api-version": API_VERSION,
            "x-vscode-user-agent-library-version": "electron-fetch",
        }

    async def _get_copilot_token(self, github_token: str) -> Optional[Dict[str, Any]]:
        """Get Copilot token from GitHub token."""
        url = f"{self.GITHUB_API_BASE}{self.COPILOT_TOKEN_URL}"
        headers = self._get_github_headers(github_token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            print(f"Failed to get copilot token: {resp.status_code} {resp.text}")
            return None

        data = resp.json()
        return {
            "token": data.get("token"),
            "expires_at": data.get("expires_at"),
            "refresh_in": data.get("refresh_in"),
        }

    async def get_valid_token(self) -> Optional[str]:
        """Get valid Copilot token."""
        # Check cached token
        if self._cached_token and self._token_expires_at > time.time():
            return self._cached_token

        # Check saved token
        token_data = self._load_saved_token()
        if token_data:
            expires_at = token_data.get("expires_at", 0)
            if expires_at > time.time():
                self._cached_token = token_data.get("access_token")
                self._token_expires_at = expires_at
                return self._cached_token

        # Get new token from GitHub (try multiple token sources)
        github_tokens = self._get_github_token_candidates()
        if not github_tokens:
            raise ValueError(
                "No GitHub token found. Please run 'brain_agentctl auth' to authenticate."
            )
        copilot_data = None
        selected_github_token = None
        for github_token in github_tokens:
            copilot_data = await self._get_copilot_token(github_token)
            if copilot_data and copilot_data.get("token"):
                selected_github_token = github_token
                break
            # Some accounts can call api.githubcopilot.com directly with GitHub OAuth token.
            if github_token.startswith(("ghu_", "gho_")):
                selected_github_token = github_token
                copilot_data = {
                    "token": github_token,
                    "expires_at": int(time.time()) + 3600,
                    "direct_passthrough": True,
                }
                break
        if not copilot_data or not copilot_data.get("token"):
            raise ValueError(f"Failed to get Copilot token. Tried {len(github_tokens)} GitHub token source(s).")

        # Save and cache
        copilot_token = copilot_data["token"]
        # Copilot API 返回的是 Unix timestamp
        expires_at = copilot_data.get("expires_at", int(time.time()) + 3600)

        token_data = {
            "access_token": copilot_token,
            "expires_at": expires_at,
            "github_token": selected_github_token or "",
        }
        self._save_token(token_data)

        self._cached_token = copilot_token
        self._token_expires_at = expires_at

        return copilot_token

    def _get_copilot_headers(
        self,
        token: str,
        enable_vision: bool = False,
        initiator: str = "user",
    ) -> Dict[str, str]:
        """Build headers for Copilot API calls (参考 copilot-api)."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "copilot-integration-id": "vscode-chat",
            "editor-version": f"vscode/{VSCODE_VERSION}",
            "editor-plugin-version": EDITOR_PLUGIN_VERSION,
            "user-agent": USER_AGENT,
            "openai-intent": "conversation-panel",
            "x-github-api-version": API_VERSION,
            "x-request-id": str(uuid.uuid4()),
            "x-vscode-user-agent-library-version": "electron-fetch",
            "X-Initiator": initiator,
        }
        if enable_vision:
            headers["copilot-vision-request"] = "true"
        return headers

    def _map_stop_reason(self, finish_reason: Optional[str]) -> str:
        mapping = {
            "stop": "end_turn",
            "length": "max_tokens",
            "content_filter": "stop_sequence",
            "tool_calls": "tool_use",
        }
        return mapping.get((finish_reason or "").lower(), "end_turn")

    def _canonicalize_model(self, model: str) -> str:
        raw = (model or "").strip()
        if not raw:
            return raw
        _, _, maybe_model = raw.partition("/")
        core_model = maybe_model if maybe_model else raw
        return self.MODEL_ALIASES.get(core_model, core_model)

    @staticmethod
    def _is_model_not_supported(status_code: int, body_text: str) -> bool:
        if status_code not in (400, 404):
            return False
        txt = (body_text or "").lower()
        return (
            "model_not_supported" in txt
            or "unsupported_api_for_model" in txt
            or "the requested model is not supported" in txt
            or "not accessible via the /chat/completions endpoint" in txt
        )

    async def _get_model_ids(self) -> list[str]:
        now = time.time()
        if self._models_cache and (now - self._models_cache_ts) < 60:
            return self._models_cache
        models = await self.get_models()
        ids = [str(m.get("id", "") or "").strip() for m in models if isinstance(m, dict)]
        ids = [m for m in ids if m]
        self._models_cache = ids
        self._models_cache_ts = now
        return ids

    async def _fallback_model_candidates(self, current_model: str) -> list[str]:
        current = self._canonicalize_model(current_model)
        available = await self._get_model_ids()
        if not available:
            return []
        out: list[str] = []
        seen = {current}
        for candidate in self.MODEL_FALLBACK_PREFERENCE:
            if candidate in available and candidate not in seen:
                out.append(candidate)
                seen.add(candidate)
        for mid in available:
            if mid not in seen:
                out.append(mid)
                seen.add(mid)
        return out

    def _extract_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            ctype = content.get("type")
            if ctype == "text":
                return str(content.get("text", ""))
            if ctype == "thinking":
                return str(content.get("thinking", ""))
            if ctype == "tool_result":
                return self._extract_text(content.get("content", ""))
            # Best-effort fallback for unknown content blocks.
            return self._extract_text(content.get("content", ""))
        if isinstance(content, list):
            parts = []
            for block in content:
                part = self._extract_text(block)
                if part:
                    parts.append(part)
            return "\n\n".join([p for p in parts if p])
        return str(content or "")

    def _map_content_for_openai(self, content: Any) -> Any:
        """Map Anthropic content blocks to OpenAI content format (supports image/thinking)."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            ctype = content.get("type")
            if ctype == "text":
                return {"type": "text", "text": str(content.get("text", ""))}
            if ctype == "thinking":
                return {"type": "text", "text": str(content.get("thinking", ""))}
            if ctype == "image":
                src = content.get("source", {}) or {}
                media_type = src.get("media_type", "image/png")
                data = src.get("data", "")
                if data:
                    return {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    }
                return None
            if ctype == "tool_result":
                return self._map_content_for_openai(content.get("content", ""))
            return self._map_content_for_openai(content.get("content", ""))
        if isinstance(content, list):
            blocks = []
            has_image = False
            for block in content:
                mapped = self._map_content_for_openai(block)
                if not mapped:
                    continue
                if isinstance(mapped, dict):
                    if mapped.get("type") == "image_url":
                        has_image = True
                    blocks.append(mapped)
                elif isinstance(mapped, str):
                    blocks.append({"type": "text", "text": mapped})
            if not blocks:
                return ""
            if has_image:
                return blocks
            return "\n\n".join(
                b.get("text", "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return str(content or "")

    def _is_agent_call(self, payload: Dict[str, Any]) -> bool:
        """Match copilot-api behavior: assistant/tool role means agent call."""
        for msg in payload.get("messages", []) or []:
            role = msg.get("role")
            if role in ("assistant", "tool"):
                return True
        return False

    def _has_vision_content(self, payload: Dict[str, Any]) -> bool:
        for msg in payload.get("messages", []) or []:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        return True
        return False

    def _translate_anthropic_to_openai(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        system = payload.get("system")
        messages = []
        if system:
            messages.append({"role": "system", "content": self._map_content_for_openai(system)})

        for msg in payload.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user" and isinstance(content, list):
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                non_tool = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result")]
                if non_tool:
                    messages.append({"role": "user", "content": self._map_content_for_openai(non_tool)})
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": self._map_content_for_openai(tr.get("content", "")),
                    })
                continue

            if role == "assistant" and isinstance(content, list):
                text_blocks = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") in ("text", "thinking")
                ]
                tool_use_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": self._map_content_for_openai(text_blocks),
                }
                if tool_use_blocks:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": b.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                            },
                        }
                        for b in tool_use_blocks
                    ]
                messages.append(assistant_msg)
                continue

            messages.append({"role": role, "content": self._map_content_for_openai(content)})

        out: Dict[str, Any] = {
            "model": payload.get("model"),
            "messages": messages,
            "stream": payload.get("stream", False),
        }
        if payload.get("max_tokens") is not None:
            out["max_tokens"] = payload.get("max_tokens")
        if payload.get("temperature") is not None:
            out["temperature"] = payload.get("temperature")
        if payload.get("top_p") is not None:
            out["top_p"] = payload.get("top_p")
        if payload.get("stop_sequences") is not None:
            out["stop"] = payload.get("stop_sequences")

        metadata = payload.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("user_id") is not None:
            out["user"] = metadata.get("user_id")

        tools = payload.get("tools")
        if tools:
            out["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": (t.get("input_schema", {}) or {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]
            # Ensure function parameter schemas are OpenAI-compatible.
            for item in out["tools"]:
                fn = item.get("function", {})
                params = fn.get("parameters")
                if not isinstance(params, dict):
                    fn["parameters"] = {"type": "object", "properties": {}}
                    continue
                if params.get("type") == "object" and "properties" not in params:
                    params["properties"] = {}
                if params.get("type") is None and "properties" not in params:
                    params["type"] = "object"
                    params["properties"] = {}
                if not isinstance(params.get("properties"), dict):
                    params["properties"] = {}

        tool_choice = payload.get("tool_choice")
        if isinstance(tool_choice, dict):
            tc_type = tool_choice.get("type")
            if tc_type == "auto":
                out["tool_choice"] = "auto"
            elif tc_type == "any":
                out["tool_choice"] = "required"
            elif tc_type == "none":
                out["tool_choice"] = "none"
            elif tc_type == "tool" and tool_choice.get("name"):
                out["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice.get("name")},
                }
        return out

    def _normalize_messages_response(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
        usage = data.get("usage", {}) or {}
        return {
            "id": data.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            "model": data.get("model", model),
            "content": data.get("content", []),
            "stop_reason": data.get("stop_reason", "end_turn"),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    def _translate_openai_to_messages_normalized(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        content_blocks = []
        if message.get("content"):
            content_blocks.append({"type": "text", "text": message.get("content", "")})
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", "{}")
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except Exception:
                parsed = {}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                "name": fn.get("name", ""),
                "input": parsed if isinstance(parsed, dict) else {},
            })

        usage = data.get("usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        cached_tokens = (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        out = {
            "id": data.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            "model": model,
            "content": content_blocks,
            "stop_reason": self._map_stop_reason(choice.get("finish_reason")),
            "input_tokens": max(0, prompt_tokens - cached_tokens),
            "output_tokens": completion_tokens,
        }
        if cached_tokens:
            out["cache_read_input_tokens"] = cached_tokens
        return out

    async def forward(self, request: Dict[str, Any], protocol: str = "chat_completions") -> Dict[str, Any]:
        """Forward request to Copilot API.

        Args:
            request: The request body
            protocol: One of "chat_completions", "messages", "responses"
        """
        token = await self.get_valid_token()
        original_model = str(request.get("model", "") or "")
        request = dict(request)
        request["model"] = self._canonicalize_model(original_model)

        # Select endpoint based on protocol
        # Copilot API supports both /v1/messages and /chat/completions
        if protocol == "messages":
            # Prefer native Anthropic endpoint.
            url = f"{self._get_copilot_api_base()}/v1/messages"
            headers = self._get_copilot_headers(
                token,
                initiator="agent" if self._is_agent_call(request) else "user",
            )
            headers["anthropic-version"] = "2023-06-01"
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=request, headers=headers)

            if resp.status_code == 200:
                return self._normalize_messages_response(resp.json(), original_model or request.get("model", ""))

            # Some models (e.g. GPT family) are unavailable on /v1/messages.
            # Fallback to /chat/completions with protocol translation.
            if resp.status_code in (400, 404):
                payload = self._translate_anthropic_to_openai(request)
                chat_url = f"{self._get_copilot_api_base()}/chat/completions"
                chat_headers = self._get_copilot_headers(
                    token,
                    enable_vision=self._has_vision_content(payload),
                    initiator="agent" if self._is_agent_call(payload) else "user",
                )
                async with httpx.AsyncClient(timeout=120.0) as client:
                    chat_resp = await client.post(chat_url, json=payload, headers=chat_headers)
                if chat_resp.status_code == 200:
                    return self._translate_openai_to_messages_normalized(
                        chat_resp.json(),
                        original_model or request.get("model", ""),
                    )
                raise ValueError(f"Copilot API error: {chat_resp.status_code} {chat_resp.text}")

            raise ValueError(f"Copilot API error: {resp.status_code} {resp.text}")
        else:
            url = f"{self._get_copilot_api_base()}/chat/completions"
            headers = self._get_copilot_headers(
                token,
                enable_vision=self._has_vision_content(request),
                initiator="agent" if self._is_agent_call(request) else "user",
            )

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=request, headers=headers)

        if resp.status_code == 401:
            # Token expired, clear cache and retry
            self._cached_token = None
            self._token_expires_at = 0
            self._get_token_file().unlink(missing_ok=True)
            raise ValueError("Token expired. Please try again.")

        if resp.status_code != 200:
            raise ValueError(f"Copilot API error: {resp.status_code} {resp.text}")

        return resp.json()

    async def forward_stream(self, request: Dict[str, Any], protocol: str = "chat_completions"):
        """Forward request in streaming mode and yield raw SSE bytes."""
        token = await self.get_valid_token()
        request = dict(request)
        request["model"] = self._canonicalize_model(str(request.get("model", "") or ""))

        if protocol == "messages":
            # For compatibility across model families, stream from chat/completions
            # and let upper layer translate SSE events to Anthropic format.
            url = f"{self._get_copilot_api_base()}/chat/completions"
            request = self._translate_anthropic_to_openai(request)
            request["stream"] = True
            headers = self._get_copilot_headers(
                token,
                enable_vision=self._has_vision_content(request),
                initiator="agent" if self._is_agent_call(request) else "user",
            )
        else:
            url = f"{self._get_copilot_api_base()}/chat/completions"
            headers = self._get_copilot_headers(
                token,
                enable_vision=self._has_vision_content(request),
                initiator="agent" if self._is_agent_call(request) else "user",
            )

        async def _stream_once(payload: Dict[str, Any]):
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 401:
                        self._cached_token = None
                        self._token_expires_at = 0
                        self._get_token_file().unlink(missing_ok=True)
                        raise ValueError("Token expired. Please try again.")
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "ignore")
                        raise ValueError(f"Copilot API error: {resp.status_code} {body}")
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk

        async for chunk in _stream_once(request):
            yield chunk

    async def forward_embeddings(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Forward embeddings request to Copilot embeddings endpoint."""
        token = await self.get_valid_token()
        url = f"{self._get_copilot_api_base()}/embeddings"
        headers = self._get_copilot_headers(token)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=request, headers=headers)

        if resp.status_code == 401:
            self._cached_token = None
            self._token_expires_at = 0
            self._get_token_file().unlink(missing_ok=True)
            raise ValueError("Token expired. Please try again.")
        if resp.status_code != 200:
            raise ValueError(f"Copilot API error: {resp.status_code} {resp.text}")
        return resp.json()

    async def get_current_token(self) -> str:
        """Return current valid Copilot token."""
        return await self.get_valid_token()

    async def get_usage(self) -> Dict[str, Any]:
        """Fetch Copilot usage/quota snapshot from GitHub API."""
        github_token = self._get_github_token()
        if not github_token:
            raise ValueError("No GitHub token found for usage query.")
        headers = self._get_github_headers(github_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.GITHUB_API_BASE}/copilot_internal/user", headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Failed to fetch usage: {resp.status_code} {resp.text}")
        return resp.json()

    async def get_models(self) -> list:
        """动态获取模型列表."""
        token = await self.get_valid_token()
        if not token:
            return []

        headers = self._get_copilot_headers(token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._get_copilot_api_base()}/models",
                headers=headers,
            )

        if resp.status_code != 200:
            return []

        data = resp.json()
        models = []
        for m in data.get("data", []):
            policy = m.get("policy", {})
            # 只返回启用的模型
            if policy.get("state") != "disabled":
                models.append({
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "vendor": m.get("vendor"),
                })
        return models

    async def health_check(self) -> bool:
        """Check if Copilot API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._get_copilot_api_base()}/models", timeout=5.0)
                return resp.status_code == 200
        except Exception:
            return False

    def get_api_base_url(self) -> str:
        return self._get_copilot_api_base()
