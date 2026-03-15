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
    OPENAI_TOOL_NAME_MAX_LEN = 64
    OPENAI_RETRY_MAX_MESSAGES = 120
    OPENAI_RETRY_TARGET_CHARS = 320000

    # Token 刷新阈值：在过期前多少秒主动刷新（默认 10 分钟）
    TOKEN_REFRESH_LEEWAY_SECONDS = 600

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
        self._token_refresh_at: float = 0  # 建议刷新时间（来自 refresh_in）
        self._last_token_error: str = ""
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

    def _compute_refresh_at(self, refresh_in: Optional[int], now: float, expires_at: int) -> int:
        """Normalize refresh_in to an absolute Unix timestamp.

        Historical token files stored `refresh_in` as relative seconds while newer
        files store the computed refresh timestamp.
        """
        if not refresh_in:
            return max(0, int(expires_at) - self.TOKEN_REFRESH_LEEWAY_SECONDS)
        value = int(refresh_in)
        if value < 10_000_000:
            return int(now) + value
        return value

    async def _refresh_github_oauth_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """使用 refresh_token 刷新 GitHub OAuth token.

        返回新的 token 数据，包含 access_token, refresh_token, expires_at 等。
        """
        # 获取配置中的 client_id 和 client_secret
        client_id = os.environ.get("GITHUB_CLIENT_ID", "Iv1.b507a08c87ecfe98")
        client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")

        if not client_secret:
            print("[copilot] GITHUB_CLIENT_SECRET not set, cannot refresh OAuth token")
            return None

        url = "https://github.com/login/oauth/access_token"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, data=data)

            if resp.status_code != 200:
                self._last_token_error = f"GitHub OAuth refresh failed: {resp.status_code} {resp.text}"
                print(f"[copilot] {self._last_token_error}")
                return None

            result = resp.json()
            if "error" in result:
                self._last_token_error = f"GitHub OAuth refresh error: {result.get('error_description', result['error'])}"
                print(f"[copilot] {self._last_token_error}")
                return None

            # 计算过期时间
            expires_in = result.get("expires_in", 28800)  # 默认 8 小时
            expires_at = int(time.time()) + expires_in

            return {
                "access_token": result.get("access_token"),
                "refresh_token": result.get("refresh_token", refresh_token),  # 有些刷新不会返回新的 refresh_token
                "token_type": result.get("token_type", "bearer"),
                "expires_at": expires_at,
                "scope": result.get("scope", ""),
            }
        except Exception as e:
            self._last_token_error = f"GitHub OAuth refresh exception: {e}"
            print(f"[copilot] Exception refreshing OAuth token: {e}")
            return None

    def _load_github_oauth_data(self) -> Optional[Dict[str, Any]]:
        """加载保存的 GitHub OAuth 数据（包含 refresh_token）."""
        github_oauth_file = self._token_dir / "github_oauth.json"
        if not github_oauth_file.exists():
            return None
        try:
            with open(github_oauth_file) as f:
                return json.load(f)
        except Exception:
            return None

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
            self._last_token_error = f"Copilot token exchange failed: {resp.status_code} {resp.text}"
            print(f"[copilot] {self._last_token_error}")
            return None

        data = resp.json()
        return {
            "token": data.get("token"),
            "expires_at": data.get("expires_at"),
            "refresh_in": data.get("refresh_in"),
        }

    async def get_valid_token(self) -> Optional[str]:
        """Get valid Copilot token with proactive refresh support."""
        now = time.time()
        self._last_token_error = ""

        # Check cached token (使用 refresh_at 作为提前刷新阈值)
        if self._cached_token:
            refresh_deadline = self._token_refresh_at or (self._token_expires_at - self.TOKEN_REFRESH_LEEWAY_SECONDS)
            if now < refresh_deadline:
                return self._cached_token
            # Token 即将过期，尝试刷新
            print(f"[copilot] Token approaching expiration (refresh_at={self._token_refresh_at}, expires_at={self._token_expires_at}), refreshing...")

        # Check saved token
        saved_access_token = ""
        saved_expires_at = 0
        saved_refresh_at = 0
        token_data = self._load_saved_token()
        if token_data:
            saved_access_token = str(token_data.get("access_token", "") or "").strip()
            saved_expires_at = int(token_data.get("expires_at", 0) or 0)
            saved_refresh_at = self._compute_refresh_at(token_data.get("refresh_in"), now, saved_expires_at)

            if saved_access_token and now < saved_refresh_at and now < saved_expires_at:
                # Token 仍在安全窗口内，直接复用。
                self._cached_token = saved_access_token
                self._token_expires_at = saved_expires_at
                self._token_refresh_at = saved_refresh_at
                return self._cached_token

            print(f"[copilot] Saved token approaching expiration, refreshing...")

        # 尝试刷新 GitHub OAuth token（如果是 ghu_/gho_ 类型的 token）
        oauth_data = self._load_github_oauth_data()
        if oauth_data:
            github_token = oauth_data.get("github_token", "").strip()
            refresh_token = oauth_data.get("refresh_token", "").strip()
            token_expires_at = oauth_data.get("expires_at", 0)

            # 如果 OAuth token 即将过期或已过期，且我们有 refresh_token，尝试刷新
            if refresh_token and (now >= token_expires_at - self.TOKEN_REFRESH_LEEWAY_SECONDS):
                print(f"[copilot] GitHub OAuth token expiring, attempting refresh...")
                new_oauth = await self._refresh_github_oauth_token(refresh_token)
                if new_oauth and new_oauth.get("access_token"):
                    # 更新 github_oauth.json
                    oauth_data.update({
                        "github_token": new_oauth["access_token"],
                        "refresh_token": new_oauth.get("refresh_token", refresh_token),
                        "expires_at": new_oauth["expires_at"],
                        "token_type": new_oauth.get("token_type", "bearer"),
                    })
                    github_oauth_file = self._token_dir / "github_oauth.json"
                    with open(github_oauth_file, "w") as f:
                        json.dump(oauth_data, f, indent=2)
                    print(f"[copilot] GitHub OAuth token refreshed successfully")
                    # 使用新 token 继续获取 Copilot token
                    copilot_data = await self._get_copilot_token(new_oauth["access_token"])
                    if copilot_data and copilot_data.get("token"):
                        return await self._save_and_cache_token(
                            copilot_data["token"],
                            copilot_data.get("expires_at"),
                            copilot_data.get("refresh_in"),
                            new_oauth["access_token"]
                        )

        # Get new token from GitHub (try multiple token sources)
        github_tokens = self._get_github_token_candidates()
        if not github_tokens:
            raise ValueError(
                "No GitHub token found. Please run 'brain_agentctl auth' to authenticate."
            )

        copilot_data = None
        selected_github_token = None
        passthrough_token = None

        for github_token in github_tokens:
            copilot_data = await self._get_copilot_token(github_token)
            if copilot_data and copilot_data.get("token"):
                selected_github_token = github_token
                break
            # Some accounts can call api.githubcopilot.com directly with GitHub OAuth token.
            if not passthrough_token and github_token.startswith(("ghu_", "gho_")):
                passthrough_token = github_token

        if not copilot_data or not copilot_data.get("token"):
            if saved_access_token and now < saved_expires_at:
                retry_at = min(saved_expires_at, int(now) + 60)
                print(
                    f"[copilot] Refresh failed; using saved token until expires_at={saved_expires_at} "
                    f"(retry_at={retry_at})"
                )
                self._cached_token = saved_access_token
                self._token_expires_at = saved_expires_at
                self._token_refresh_at = retry_at
                return self._cached_token

        if (not copilot_data or not copilot_data.get("token")) and passthrough_token:
            selected_github_token = passthrough_token
            # 对于 passthrough token，检查是否需要刷新 OAuth
            # 注意：passthrough token 无法通过 _get_copilot_token 刷新，需要 OAuth 刷新
            copilot_data = {
                "token": passthrough_token,
                "expires_at": int(time.time()) + 3600,
                "direct_passthrough": True,
            }

        if not copilot_data or not copilot_data.get("token"):
            detail = f" Last error: {self._last_token_error}" if self._last_token_error else ""
            raise ValueError(
                f"Failed to get Copilot token. Tried {len(github_tokens)} GitHub token source(s).{detail}"
            )

        return await self._save_and_cache_token(
            copilot_data["token"],
            copilot_data.get("expires_at"),
            copilot_data.get("refresh_in"),
            selected_github_token
        )

    async def _save_and_cache_token(
        self,
        copilot_token: str,
        expires_at: Optional[int],
        refresh_in: Optional[int],
        github_token: Optional[str]
    ) -> str:
        """Save token to disk and update cache."""
        now = time.time()

        # expires_at is a Unix timestamp; refresh_in is relative seconds.
        if not expires_at:
            expires_at = int(now) + 3600

        # 计算刷新时间点
        refresh_at = self._compute_refresh_at(refresh_in, now, expires_at)

        token_data = {
            "access_token": copilot_token,
            "expires_at": expires_at,
            "refresh_in": refresh_at,  # 保存计算后的刷新时间点
            "github_token": github_token or "",
        }
        self._save_token(token_data)

        self._cached_token = copilot_token
        self._token_expires_at = expires_at
        self._token_refresh_at = refresh_at

        print(f"[copilot] Token cached, expires_at={expires_at}, refresh_at={refresh_at}")

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

    def _prefers_native_messages(self, model: str) -> bool:
        core_model = self._canonicalize_model(model).lower()
        return not (
            core_model.startswith("gpt-")
            or core_model.startswith("grok-")
            or core_model.startswith("text-embedding-")
            or core_model.startswith("oswe-")
        )

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

    def _sanitize_openai_tool_transcript(self, messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """Drop dangling or out-of-order tool call state before sending to Copilot.

        Copilot enforces the OpenAI tool-call contract strictly:
        assistant.tool_calls must be followed immediately by matching tool messages.
        Claude transcripts can contain interrupted turns where that invariant no longer
        holds. In that case, preserve the assistant text but strip invalid tool state.
        """
        sanitized: list[Dict[str, Any]] = []
        idx = 0

        while idx < len(messages):
            msg = messages[idx]
            if not isinstance(msg, dict):
                idx += 1
                continue

            role = msg.get("role")
            tool_calls = msg.get("tool_calls")

            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                expected_ids: list[str] = []
                normalized_calls: list[Dict[str, Any]] = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    tc_id = str(tc.get("id", "") or "").strip()
                    if not tc_id or tc_id in expected_ids:
                        continue
                    expected_ids.append(tc_id)
                    normalized_calls.append(tc)

                lookahead = idx + 1
                immediate_tool_messages: list[Dict[str, Any]] = []
                matched_ids: set[str] = set()

                while lookahead < len(messages):
                    next_msg = messages[lookahead]
                    if not isinstance(next_msg, dict) or next_msg.get("role") != "tool":
                        break
                    tc_id = str(next_msg.get("tool_call_id", "") or "").strip()
                    if tc_id in expected_ids and tc_id not in matched_ids:
                        immediate_tool_messages.append(next_msg)
                        matched_ids.add(tc_id)
                    lookahead += 1

                valid_calls = [tc for tc in normalized_calls if str(tc.get("id", "") or "").strip() in matched_ids]
                updated = dict(msg)
                if valid_calls:
                    updated["tool_calls"] = valid_calls
                    sanitized.append(updated)
                    sanitized.extend(immediate_tool_messages)
                else:
                    updated.pop("tool_calls", None)
                    if updated.get("content") is None:
                        updated["content"] = ""
                    sanitized.append(updated)

                if set(matched_ids) != set(expected_ids):
                    missing = [tc_id for tc_id in expected_ids if tc_id not in matched_ids]
                    print(f"[copilot] Warning: dropping dangling tool_calls: {missing}")

                idx = idx + 1
                while idx < len(messages):
                    maybe_tool = messages[idx]
                    if not isinstance(maybe_tool, dict) or maybe_tool.get("role") != "tool":
                        break
                    idx += 1
                continue

            if role == "tool":
                tc_id = str(msg.get("tool_call_id", "") or "").strip()
                if tc_id:
                    print(f"[copilot] Warning: dropping stray tool message without preceding assistant tool_calls: {tc_id}")
                idx += 1
                continue

            sanitized.append(msg)
            idx += 1

        return sanitized

    def _sanitize_anthropic_messages_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Drop dangling tool_use/tool_result blocks for Copilot native /v1/messages."""
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return payload

        sanitized: list[Dict[str, Any]] = []
        idx = 0

        while idx < len(messages):
            msg = messages[idx]
            if not isinstance(msg, dict):
                idx += 1
                continue

            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant" and isinstance(content, list):
                tool_uses = [
                    block for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_use"
                ]
                if tool_uses:
                    expected_ids = [
                        str(block.get("id", "") or "").strip()
                        for block in tool_uses
                        if str(block.get("id", "") or "").strip()
                    ]
                    matched_ids: set[str] = set()
                    next_msg = messages[idx + 1] if idx + 1 < len(messages) else None

                    if (
                        isinstance(next_msg, dict)
                        and next_msg.get("role") == "user"
                        and isinstance(next_msg.get("content"), list)
                    ):
                        for block in next_msg.get("content", []) or []:
                            if not isinstance(block, dict) or block.get("type") != "tool_result":
                                continue
                            tool_use_id = str(block.get("tool_use_id", "") or "").strip()
                            if tool_use_id in expected_ids:
                                matched_ids.add(tool_use_id)

                    updated_content = []
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            updated_content.append(block)
                            continue
                        tool_use_id = str(block.get("id", "") or "").strip()
                        if tool_use_id in matched_ids:
                            updated_content.append(block)

                    updated_msg = dict(msg)
                    updated_msg["content"] = updated_content or [{"type": "text", "text": ""}]
                    sanitized.append(updated_msg)

                    if set(matched_ids) != set(expected_ids):
                        missing = [tool_use_id for tool_use_id in expected_ids if tool_use_id not in matched_ids]
                        print(f"[copilot] Warning: dropping dangling anthropic tool_use blocks: {missing}")

                    if (
                        isinstance(next_msg, dict)
                        and next_msg.get("role") == "user"
                        and isinstance(next_msg.get("content"), list)
                    ):
                        filtered_user_content = []
                        for block in next_msg.get("content", []) or []:
                            if not isinstance(block, dict) or block.get("type") != "tool_result":
                                filtered_user_content.append(block)
                                continue
                            tool_use_id = str(block.get("tool_use_id", "") or "").strip()
                            if tool_use_id in matched_ids:
                                filtered_user_content.append(block)

                        if filtered_user_content:
                            updated_user = dict(next_msg)
                            updated_user["content"] = filtered_user_content
                            sanitized.append(updated_user)
                        idx += 2
                        continue

                    idx += 1
                    continue

            if role == "user" and isinstance(content, list):
                filtered_user_content = []
                dropped_tool_results = []
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        filtered_user_content.append(block)
                        continue
                    dropped_tool_results.append(str(block.get("tool_use_id", "") or "").strip())

                if dropped_tool_results:
                    print(f"[copilot] Warning: dropping stray anthropic tool_result blocks: {dropped_tool_results}")
                if filtered_user_content:
                    updated_msg = dict(msg)
                    updated_msg["content"] = filtered_user_content
                    sanitized.append(updated_msg)
                idx += 1
                continue

            sanitized.append(msg)
            idx += 1

        out = dict(payload)
        out["messages"] = sanitized
        return out

    @classmethod
    def _alias_tool_name(cls, name: str) -> str:
        if len(name) <= cls.OPENAI_TOOL_NAME_MAX_LEN:
            return name
        digest = uuid.uuid5(uuid.NAMESPACE_URL, name).hex[:10]
        reserve = len("__") + len(digest)
        prefix_len = max(1, cls.OPENAI_TOOL_NAME_MAX_LEN - reserve)
        return f"{name[:prefix_len]}__{digest}"

    @classmethod
    def _sanitize_tool_schema(cls, schema: Any) -> Any:
        if isinstance(schema, list):
            return [cls._sanitize_tool_schema(item) for item in schema]
        if isinstance(schema, dict):
            out = {}
            for key, value in schema.items():
                if key in {"$schema", "default", "examples", "example", "title"}:
                    continue
                if key == "additionalProperties":
                    if isinstance(value, bool):
                        out[key] = value
                    elif isinstance(value, dict):
                        # Copilot's /chat/completions endpoint rejects object-valued
                        # additionalProperties in some tool schemas. Keep the schema
                        # permissive without forwarding unsupported nested shapes.
                        out[key] = bool(value)
                    continue
                if key == "required":
                    if isinstance(value, list):
                        out[key] = [str(item) for item in value if isinstance(item, str)]
                    continue
                out[key] = cls._sanitize_tool_schema(value)
            if out.get("type") == "object" and "properties" not in out:
                out["properties"] = {}
            if out.get("type") is None and isinstance(out.get("properties"), dict):
                out["type"] = "object"
            if "properties" in out and not isinstance(out.get("properties"), dict):
                out["properties"] = {}
            return out
        return schema

    def _prepare_openai_tools(
        self,
        tools: Any,
        tool_choice: Any,
    ) -> tuple[list[Dict[str, Any]], Any, Dict[str, str]]:
        alias_to_original: Dict[str, str] = {}
        original_to_alias: Dict[str, str] = {}
        prepared: list[Dict[str, Any]] = []

        if not isinstance(tools, list):
            return prepared, tool_choice, alias_to_original

        for t in tools:
            if not isinstance(t, dict):
                continue
            fn_payload = t.get("function") if isinstance(t.get("function"), dict) else None
            original_name = ""
            description = ""
            parameters: Any = {"type": "object", "properties": {}}

            if isinstance(t.get("name"), str):
                original_name = str(t.get("name", "") or "").strip()
                description = str(t.get("description", "") or "")
                parameters = t.get("input_schema", {}) or {"type": "object", "properties": {}}
            elif fn_payload is not None:
                original_name = str(fn_payload.get("name", "") or "").strip()
                description = str(fn_payload.get("description", "") or "")
                parameters = fn_payload.get("parameters", {}) or {"type": "object", "properties": {}}

            if not original_name:
                continue
            aliased_name = self._alias_tool_name(original_name)
            if aliased_name != original_name:
                alias_to_original[aliased_name] = original_name
                original_to_alias[original_name] = aliased_name
            prepared.append(
                {
                    "type": "function",
                    "function": {
                        "name": aliased_name,
                        "description": description,
                        "parameters": self._sanitize_tool_schema(parameters),
                    },
                }
            )

        adjusted_tool_choice = tool_choice
        if isinstance(tool_choice, dict):
            adjusted_tool_choice = dict(tool_choice)
            if adjusted_tool_choice.get("type") == "tool" and adjusted_tool_choice.get("name") in original_to_alias:
                adjusted_tool_choice["name"] = original_to_alias[adjusted_tool_choice["name"]]
            elif adjusted_tool_choice.get("type") == "function":
                fn = adjusted_tool_choice.get("function")
                if isinstance(fn, dict) and fn.get("name") in original_to_alias:
                    adjusted_fn = dict(fn)
                    adjusted_fn["name"] = original_to_alias[fn["name"]]
                    adjusted_tool_choice["function"] = adjusted_fn

        return prepared, adjusted_tool_choice, alias_to_original

    @staticmethod
    def _is_prompt_too_large_error(body_text: str) -> bool:
        text = (body_text or "").lower()
        return (
            "model_max_prompt_tokens_exceeded" in text
            or "prompt token count" in text
            or "context_length_exceeded" in text
        )

    def _prepare_chat_completions_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(request)
        messages = prepared.get("messages")
        if isinstance(messages, list):
            prepared["messages"] = self._sanitize_openai_tool_transcript(messages)

        alias_to_original: Dict[str, str] = {}
        tools = prepared.get("tools")
        normalized_tools, normalized_tool_choice, alias_to_original = self._prepare_openai_tools(
            tools,
            prepared.get("tool_choice"),
        )
        if normalized_tools:
            prepared["tools"] = normalized_tools
            prepared["tool_choice"] = normalized_tool_choice
        elif "tools" in prepared:
            prepared.pop("tools", None)
            prepared.pop("tool_choice", None)

        if alias_to_original:
            prepared["_tool_alias_map"] = alias_to_original
        return prepared

    def _trim_chat_completions_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        messages = request.get("messages")
        if not isinstance(messages, list) or len(messages) <= self.OPENAI_RETRY_MAX_MESSAGES:
            approx_chars = len(json.dumps(request, ensure_ascii=False))
            if approx_chars <= self.OPENAI_RETRY_TARGET_CHARS:
                return None

        system_prefix: list[Dict[str, Any]] = []
        non_system: list[Dict[str, Any]] = []
        for idx, msg in enumerate(messages or []):
            if (
                idx == len(system_prefix)
                and isinstance(msg, dict)
                and str(msg.get("role", "") or "") == "system"
            ):
                system_prefix.append(msg)
            else:
                non_system.append(msg)

        if len(non_system) <= 8:
            return None

        trimmed_tail = list(non_system)
        while (
            len(trimmed_tail) > self.OPENAI_RETRY_MAX_MESSAGES
            or len(json.dumps({"messages": system_prefix + trimmed_tail}, ensure_ascii=False)) > self.OPENAI_RETRY_TARGET_CHARS
        ):
            if len(trimmed_tail) <= 8:
                return None
            trimmed_tail = trimmed_tail[1:]

        trimmed = dict(request)
        trimmed["messages"] = self._sanitize_openai_tool_transcript(system_prefix + trimmed_tail)
        return trimmed

    @staticmethod
    def _restore_tool_aliases_in_response(result: Dict[str, Any], alias_to_original: Dict[str, str]) -> None:
        if not alias_to_original:
            return

        content = result.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                if isinstance(name, str) and name in alias_to_original:
                    block["name"] = alias_to_original[name]

        choices = result.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                for container_key in ("message", "delta"):
                    message = choice.get(container_key)
                    if not isinstance(message, dict):
                        continue
                    for tc in message.get("tool_calls", []) or []:
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function")
                        if not isinstance(fn, dict):
                            continue
                        name = fn.get("name")
                        if isinstance(name, str) and name in alias_to_original:
                            fn["name"] = alias_to_original[name]

    def _summarize_request(self, request: Dict[str, Any], protocol: str) -> Dict[str, Any]:
        messages_summary = []
        for idx, msg in enumerate(request.get("messages", []) or []):
            if not isinstance(msg, dict):
                messages_summary.append({"idx": idx, "type": type(msg).__name__})
                continue
            content = msg.get("content")
            content_types = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        content_types.append(str(block.get("type", "dict")))
                    else:
                        content_types.append(type(block).__name__)
            else:
                content_types.append(type(content).__name__)
            messages_summary.append({
                "idx": idx,
                "role": msg.get("role"),
                "content_types": content_types,
                "tool_calls": len(msg.get("tool_calls", []) or []),
            })

        tools = request.get("tools") or []
        tool_names = []
        if isinstance(tools, list):
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name")
                if not name and isinstance(tool.get("function"), dict):
                    name = tool["function"].get("name")
                if name:
                    tool_names.append(str(name))

        return {
            "protocol": protocol,
            "model": request.get("model"),
            "stream": request.get("stream"),
            "message_count": len(request.get("messages", []) or []),
            "messages": messages_summary,
            "tools": tool_names,
            "tool_choice": request.get("tool_choice"),
            "metadata_keys": sorted((request.get("metadata") or {}).keys()) if isinstance(request.get("metadata"), dict) else [],
        }

    def _dump_failed_request(self, request: Dict[str, Any], protocol: str, body_text: str) -> None:
        debug_dir = Path("/tmp/brain_agent_proxy_debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        req_path = debug_dir / f"copilot_failed_request_{stamp}.json"
        meta_path = debug_dir / f"copilot_failed_request_{stamp}.meta.json"
        try:
            req_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
            meta = self._summarize_request(request, protocol)
            meta["upstream_error"] = body_text
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[copilot] Debug dump written: {req_path} {meta_path}")
            print(f"[copilot] Request summary: {json.dumps(meta, ensure_ascii=False)}")
        except Exception as exc:
            print(f"[copilot] Failed to write debug dump: {exc}")

    def _translate_anthropic_to_openai(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        system = payload.get("system")
        messages = []
        if system:
            messages.append({"role": "system", "content": self._map_content_for_openai(system)})

        msg_list = payload.get("messages", [])
        for idx, msg in enumerate(msg_list):
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                if isinstance(content, list):
                    # Separate tool_results from other content
                    non_tool = []
                    tool_messages = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_use_id = block.get("tool_use_id", "")
                            if not tool_use_id:
                                print(f"[copilot] Warning: tool_result missing tool_use_id, skipping")
                                continue
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_use_id,
                                "content": self._map_content_for_openai(block.get("content", "")),
                            })
                        else:
                            non_tool.append(block)

                    # CRITICAL: Tool messages must immediately follow the assistant message that called them.
                    # In Anthropic format, tool_result blocks are in the user message that follows
                    # the assistant's tool_use. We must output tool messages BEFORE the user message.
                    if tool_messages:
                        messages.extend(tool_messages)

                    # Add user message with non-tool content (if any)
                    if non_tool:
                        messages.append({"role": "user", "content": self._map_content_for_openai(non_tool)})
                else:
                    messages.append({"role": "user", "content": self._map_content_for_openai(content)})

            elif role == "assistant" and isinstance(content, list):
                text_blocks = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") in ("text", "thinking")
                ]
                tool_use_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]

                # Build assistant message content
                assistant_content = self._map_content_for_openai(text_blocks) if text_blocks else ""

                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_content if assistant_content else None,
                }
                if assistant_msg["content"] is None:
                    assistant_msg["content"] = ""  # OpenAI requires non-null content

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

            elif role == "assistant":
                messages.append({"role": "assistant", "content": self._map_content_for_openai(content) if content else ""})

            elif role == "tool":
                # Direct tool role message (already in OpenAI format)
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": self._map_content_for_openai(content),
                })

            else:
                messages.append({"role": role, "content": self._map_content_for_openai(content)})

        # Validate: ensure all tool_calls have corresponding tool messages
        pending_tool_calls: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id:
                        pending_tool_calls.add(tc_id)
            elif msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id in pending_tool_calls:
                    pending_tool_calls.discard(tc_id)

        if pending_tool_calls:
            print(f"[copilot] Warning: {len(pending_tool_calls)} tool_call(s) without response: {pending_tool_calls}")
            # Remove tool_calls from assistant messages to avoid API error
            # This preserves the text content while avoiding the validation error
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    msg["tool_calls"] = [
                        tc for tc in msg["tool_calls"]
                        if tc.get("id") not in pending_tool_calls
                    ]
                    if not msg["tool_calls"]:
                        del msg["tool_calls"]

        messages = self._sanitize_openai_tool_transcript(messages)

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

        alias_to_original: Dict[str, str] = {}
        tools = payload.get("tools")
        prepared_tools, tool_choice, alias_to_original = self._prepare_openai_tools(
            tools,
            payload.get("tool_choice"),
        )
        if prepared_tools:
            out["tools"] = prepared_tools
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

        tool_choice = tool_choice
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
        if alias_to_original:
            out["_tool_alias_map"] = alias_to_original
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
            request = self._sanitize_anthropic_messages_payload(request)
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
                payload = self._prepare_chat_completions_request(self._translate_anthropic_to_openai(request))
                chat_url = f"{self._get_copilot_api_base()}/chat/completions"
                chat_headers = self._get_copilot_headers(
                    token,
                    enable_vision=self._has_vision_content(payload),
                    initiator="agent" if self._is_agent_call(payload) else "user",
                )
                retried = False
                while True:
                    outbound_payload = dict(payload)
                    alias_to_original = outbound_payload.pop("_tool_alias_map", {})
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        chat_resp = await client.post(chat_url, json=outbound_payload, headers=chat_headers)
                    if chat_resp.status_code == 200:
                        result = self._translate_openai_to_messages_normalized(
                            chat_resp.json(),
                            original_model or request.get("model", ""),
                        )
                        self._restore_tool_aliases_in_response(result, alias_to_original)
                        return result
                    if not retried and self._is_prompt_too_large_error(chat_resp.text):
                        trimmed_payload = self._trim_chat_completions_request(payload)
                        if trimmed_payload is not None:
                            payload = trimmed_payload
                            retried = True
                            continue
                    self._dump_failed_request(outbound_payload, "chat_completions", chat_resp.text)
                    raise ValueError(f"Copilot API error: {chat_resp.status_code} {chat_resp.text}")

            self._dump_failed_request(request, protocol, resp.text)
            raise ValueError(f"Copilot API error: {resp.status_code} {resp.text}")
        else:
            url = f"{self._get_copilot_api_base()}/chat/completions"
            request = self._prepare_chat_completions_request(request)
            headers = self._get_copilot_headers(
                token,
                enable_vision=self._has_vision_content(request),
                initiator="agent" if self._is_agent_call(request) else "user",
            )

        retried = False
        while True:
            outbound_request = dict(request)
            alias_to_original = outbound_request.pop("_tool_alias_map", {})
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=outbound_request, headers=headers)

            if resp.status_code == 401:
                # Token expired, clear cache and retry
                self._cached_token = None
                self._token_expires_at = 0
                self._get_token_file().unlink(missing_ok=True)
                raise ValueError("Token expired. Please try again.")

            if resp.status_code == 200:
                result = resp.json()
                self._restore_tool_aliases_in_response(result, alias_to_original)
                return result

            if not retried and self._is_prompt_too_large_error(resp.text):
                trimmed_request = self._trim_chat_completions_request(request)
                if trimmed_request is not None:
                    request = trimmed_request
                    retried = True
                    continue

            self._dump_failed_request(outbound_request, protocol, resp.text)
            raise ValueError(f"Copilot API error: {resp.status_code} {resp.text}")

    async def forward_stream(self, request: Dict[str, Any], protocol: str = "chat_completions"):
        """Forward request in streaming mode and yield raw SSE bytes."""
        token = await self.get_valid_token()
        request = dict(request)
        original_model = str(request.get("model", "") or "")
        request["model"] = self._canonicalize_model(original_model)

        if protocol == "messages":
            request = self._sanitize_anthropic_messages_payload(request)
            if self._prefers_native_messages(original_model):
                url = f"{self._get_copilot_api_base()}/v1/messages"
                request["stream"] = True
                headers = self._get_copilot_headers(
                    token,
                    enable_vision=self._has_vision_content(request),
                    initiator="agent" if self._is_agent_call(request) else "user",
                )
                headers["anthropic-version"] = "2023-06-01"
            else:
                # GPT-family models are only available via /chat/completions.
                url = f"{self._get_copilot_api_base()}/chat/completions"
                request = self._prepare_chat_completions_request(self._translate_anthropic_to_openai(request))
                request["stream"] = True
                headers = self._get_copilot_headers(
                    token,
                    enable_vision=self._has_vision_content(request),
                    initiator="agent" if self._is_agent_call(request) else "user",
                )
        else:
            url = f"{self._get_copilot_api_base()}/chat/completions"
            request = self._prepare_chat_completions_request(request)
            headers = self._get_copilot_headers(
                token,
                enable_vision=self._has_vision_content(request),
                initiator="agent" if self._is_agent_call(request) else "user",
            )

        async def _stream_once(payload: Dict[str, Any]):
            retried = False
            current_payload = dict(payload)
            while True:
                outbound_payload = dict(current_payload)
                alias_to_original = outbound_payload.pop("_tool_alias_map", {})
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("POST", url, json=outbound_payload, headers=headers) as resp:
                        if resp.status_code == 401:
                            self._cached_token = None
                            self._token_expires_at = 0
                            self._get_token_file().unlink(missing_ok=True)
                            raise ValueError("Token expired. Please try again.")
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            if not retried and self._is_prompt_too_large_error(body):
                                trimmed_payload = self._trim_chat_completions_request(current_payload)
                                if trimmed_payload is not None:
                                    current_payload = trimmed_payload
                                    retried = True
                                    continue
                            self._dump_failed_request(outbound_payload, protocol, body)
                            raise ValueError(f"Copilot API error: {resp.status_code} {body}")
                        if not alias_to_original:
                            async for chunk in resp.aiter_bytes():
                                if chunk:
                                    yield chunk
                            return
                        async for line in resp.aiter_lines():
                            if line.startswith("data:"):
                                data = line[5:].lstrip()
                                if data and data != "[DONE]":
                                    try:
                                        obj = json.loads(data)
                                    except Exception:
                                        pass
                                    else:
                                        self._restore_tool_aliases_in_response(obj, alias_to_original)
                                        line = f"data: {json.dumps(obj, ensure_ascii=False)}"
                            yield f"{line}\n".encode("utf-8")
                        return

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
