"""FastAPI application for brain_agent_proxy."""
import asyncio
from collections import deque
import copy
import hashlib
import json
import os
import re
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Header

from .config import AppConfig, get_config, reload_config
from .context_windows import get_context_window
from .observability.health import HealthChecker
from .protocol import messages, chat_completions, responses
from .protocol.base import Message
from .routing.engine import RoutingEngine

# IPC Configuration
DAEMON_SOCKET = os.environ.get("DAEMON_SOCKET", "/tmp/brain_ipc.sock")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "service-brain_agent_proxy")


def ipc_send_request(action: str, data: dict, timeout: float = 5.0) -> dict:
    """Send request to IPC daemon."""
    request = {"action": action, "data": data}
    request_json = json.dumps(request, ensure_ascii=False) + "\n"
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(DAEMON_SOCKET)
        sock.sendall(request_json.encode("utf-8"))
        data_bytes = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data_bytes += chunk
            if b"\n" in data_bytes:
                break
        sock.close()
        if not data_bytes:
            return {"status": "error", "message": "empty response"}
        return json.loads(data_bytes.decode("utf-8"))
    except Exception as e:
        return {"status": "error", "message": str(e)}


def register_service() -> bool:
    """Register service to IPC daemon."""
    result = ipc_send_request("service_register", {
        "service_name": SERVICE_NAME,
        "metadata": {"type": "llm_proxy", "version": "1.0.0"}
    })
    return result.get("status") == "ok"


def send_heartbeat() -> bool:
    """Send service heartbeat to IPC daemon."""
    result = ipc_send_request("service_heartbeat", {
        "service_name": SERVICE_NAME
    })
    return result.get("status") == "ok"


def start_heartbeat_thread(interval: int = 30):
    """Start background heartbeat thread."""
    def heartbeat_loop():
        while True:
            time.sleep(interval)
            try:
                send_heartbeat()
            except Exception:
                pass
    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return thread

# Allow any API key for local testing (skip validation)
# When "*" is in the list, any key is allowed
ALLOWED_API_KEYS = ["*"]
MODEL_ID_MODE = os.environ.get("BRAIN_AGENT_PROXY_MODEL_ID_MODE", "bare").strip().lower() or "bare"


class ProxyPolicyError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _status_code_for_exception(exc: Exception) -> int:
    text = str(exc or "").strip()
    lower = text.lower()

    match = re.search(r"provider returned\s+(\d{3})", lower)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    if "hit your limit" in lower or "rate limit" in lower or "quota" in lower:
        return 429
    if "not authenticated" in lower or "please run /login" in lower or "authentication_failed" in lower:
        return 401
    if "permission_error" in lower:
        return 403
    if "invalid params" in lower or "invalid_request_error" in lower:
        return 400
    return 500


RATE_LIMIT_SECONDS = float(os.environ.get("BRAIN_AGENT_PROXY_RATE_LIMIT_SECONDS", "0") or 0)
RATE_LIMIT_WAIT = os.environ.get("BRAIN_AGENT_PROXY_RATE_LIMIT_WAIT", "1").strip().lower() not in ("0", "false", "no")
MANUAL_APPROVAL = os.environ.get("BRAIN_AGENT_PROXY_MANUAL_APPROVAL", "0").strip().lower() in ("1", "true", "yes")
MANUAL_APPROVAL_TIMEOUT_SECONDS = int(
    os.environ.get("BRAIN_AGENT_PROXY_MANUAL_APPROVAL_TIMEOUT_SECONDS", "300") or 300
)
STREAM_CONNECT_TIMEOUT_SECONDS = float(
    os.environ.get("BRAIN_AGENT_PROXY_STREAM_CONNECT_TIMEOUT_SECONDS", "30") or 30
)
STREAM_IDLE_TIMEOUT_SECONDS = float(
    os.environ.get("BRAIN_AGENT_PROXY_STREAM_IDLE_TIMEOUT_SECONDS", "600") or 600
)
STREAM_MAX_RETRIES = int(
    os.environ.get("BRAIN_AGENT_PROXY_STREAM_MAX_RETRIES", "3") or 3
)
STREAM_RETRY_BASE_DELAY = float(
    os.environ.get("BRAIN_AGENT_PROXY_STREAM_RETRY_BASE_DELAY", "2.0") or 2.0
)
STREAM_RETRY_ON_TIMEOUT = os.environ.get(
    "BRAIN_AGENT_PROXY_STREAM_RETRY_ON_TIMEOUT", "1"
).strip().lower() not in ("0", "false", "no")
RECENT_REQUESTS_LIMIT = int(os.environ.get("BRAIN_AGENT_PROXY_RECENT_REQUESTS_LIMIT", "200") or 200)
SECRETS_ENV_PATHS = (
    "/xkagent_infra/runtime/config/.env",
    "/brain/secrets/system/agents/llm_tokens.env",
)
KIMI_DEFAULT_BETAS = os.environ.get(
    "BRAIN_AGENT_PROXY_KIMI_DEFAULT_BETAS",
    "claude-code-20250219,interleaved-thinking-2025-05-14,context-management-2025-06-27,prompt-caching-scope-2026-01-05,effort-2025-11-24",
)
KIMI_DEFAULT_BILLING_HEADER = os.environ.get(
    "BRAIN_AGENT_PROXY_KIMI_BILLING_HEADER",
    "cc_version=2.1.76.b57; cc_entrypoint=sdk-cli; cch=00000;",
)
KIMI_DEFAULT_USER_AGENT = os.environ.get(
    "BRAIN_AGENT_PROXY_KIMI_USER_AGENT",
    "claude-cli/2.1.76 (external, sdk-cli)",
)
KIMI_SYSTEM_PROMPT_PATH = os.environ.get(
    "BRAIN_AGENT_PROXY_KIMI_SYSTEM_PROMPT_PATH",
    "/xkagent_infra/brain/infrastructure/service/brain_agent_proxy/config/kimi_sdk_system_prompt.json",
)

# context window 配置已移至 context_windows.py
# 使用 get_context_window(model_id, provider_id) 查询
TRACEABLE_PATHS = {
    "/v1/messages",
    "/v1/chat/completions",
    "/chat/completions",
    "/v1/responses",
    "/v1/embeddings",
}

_rate_limit_lock = asyncio.Lock()
_last_request_ts = 0.0

_approval_lock = asyncio.Lock()
_pending_approvals: Dict[str, Dict[str, Any]] = {}
_recent_requests_lock = asyncio.Lock()
_recent_requests: deque[Dict[str, Any]] = deque(maxlen=max(1, RECENT_REQUESTS_LIMIT))
_recent_request_seq = 0


# Protocol handlers
PROTOCOL_HANDLERS = {
    "messages": messages.MessagesProtocolHandler(),
    "chat_completions": chat_completions.ChatCompletionsProtocolHandler(),
    "responses": responses.ResponsesProtocolHandler(),
}


def _normalize_model_id_mode(mode: Optional[str] = None) -> str:
    value = str(mode or MODEL_ID_MODE or "bare").strip().lower()
    if value in {"bare", "prefixed", "both"}:
        return value
    return "bare"


def _build_exposed_model_ids(model_id: str, provider_id: str, mode: Optional[str] = None) -> list[str]:
    """Return external model ids for /v1/models.

    `bare` keeps current behavior.
    `prefixed` exposes provider/model only.
    `both` exposes both ids to support migration.
    """
    bare_id = str(model_id or "").strip()
    provider = str(provider_id or "").strip()
    if not bare_id:
        return []

    prefixed_id = bare_id
    if provider and "/" not in bare_id:
        prefixed_id = f"{provider}/{bare_id}"

    selected_mode = _normalize_model_id_mode(mode)
    if selected_mode == "prefixed":
        return [prefixed_id]
    if selected_mode == "both":
        if prefixed_id == bare_id:
            return [bare_id]
        return [bare_id, prefixed_id]
    return [bare_id]


def _append_model_entries(
    models: list[Dict[str, Any]],
    *,
    model_id: str,
    provider_id: str,
    provider_type: str,
    cli_type: str,
    capabilities: list[str],
    name: str = "",
    vendor: str = "",
) -> None:
    for exposed_id in _build_exposed_model_ids(model_id, provider_id):
        entry: Dict[str, Any] = {
            "id": exposed_id,
            "object": "model",
            "provider": provider_id,
            "provider_type": provider_type,
            "cli_type": cli_type,
            "capabilities": capabilities,
            "name": name,
            "vendor": vendor,
        }
        ctx_win = get_context_window(model_id, provider_id)
        if ctx_win is not None:
            entry["context_window"] = ctx_win
        models.append(entry)


def _copilot_prefers_native_messages(model: str) -> bool:
    core_model = str(model or "").strip().lower()
    return not (
        core_model.startswith("gpt-")
        or core_model.startswith("grok-")
        or core_model.startswith("text-embedding-")
        or core_model.startswith("oswe-")
    )


async def _enforce_rate_limit() -> None:
    """Apply global rate limiting across all request paths."""
    global _last_request_ts
    if RATE_LIMIT_SECONDS <= 0:
        return

    async with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_ts if _last_request_ts > 0 else RATE_LIMIT_SECONDS
        wait_seconds = RATE_LIMIT_SECONDS - elapsed
        if wait_seconds > 0:
            if RATE_LIMIT_WAIT:
                await asyncio.sleep(wait_seconds)
            else:
                raise ProxyPolicyError(
                    f"Rate limit exceeded. Need to wait {int(wait_seconds) + 1} more seconds.",
                    status_code=429,
                )
        _last_request_ts = time.time()


async def _await_manual_approval(path: str, body: Dict[str, Any]) -> None:
    """Gate request execution until an operator approves it."""
    if not MANUAL_APPROVAL:
        return

    approval_id = uuid.uuid4().hex[:12]
    event = asyncio.Event()
    record = {
        "id": approval_id,
        "path": path,
        "model": str(body.get("model", "") or ""),
        "created_at": int(time.time()),
        "status": "pending",
        "decision": None,
        "event": event,
    }
    async with _approval_lock:
        _pending_approvals[approval_id] = record

    try:
        await asyncio.wait_for(event.wait(), timeout=MANUAL_APPROVAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        async with _approval_lock:
            rec = _pending_approvals.get(approval_id)
            if rec:
                rec["status"] = "timeout"
                rec["decision"] = "timeout"
        raise ProxyPolicyError("Manual approval timed out.", status_code=408)

    decision = str(record.get("decision", "") or "")
    if decision != "approved":
        raise ProxyPolicyError("Request denied by manual approval policy.", status_code=403)


async def _enforce_request_policies(path: str, body: Dict[str, Any]) -> None:
    await _enforce_rate_limit()
    await _await_manual_approval(path, body)


def _extract_client_key(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    """Extract routing client key from request auth headers.

    Priority:
    1) Authorization: Bearer <key>
    2) x-api-key: <key>
    """
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return token
    if x_api_key:
        token = x_api_key.strip()
        if token:
            return token
    return None


def _default_api_base_url(provider: Any) -> str:
    if getattr(provider, "id", "") == "openai":
        return "https://api.openai.com"
    return "http://127.0.0.1:4141"


def _canonicalize_upstream_model(provider: Any, model: str) -> str:
    """Map accepted external model ids to provider-native upstream model ids."""
    raw = str(model or "").strip()
    if not raw:
        return raw
    resolved = provider.resolve_model(raw) if provider else None
    if resolved:
        return resolved.upstream_name()
    return raw.split("/", 1)[1] if "/" in raw else raw


def _canonicalize_external_model(provider: Any, model: str) -> str:
    """Normalize an accepted model id/alias/upstream name to the external canonical id."""
    raw = str(model or "").strip()
    if not raw:
        return raw
    resolved = provider.resolve_model(raw) if provider else None
    if resolved:
        return resolved.id
    return raw.split("/", 1)[1] if "/" in raw else raw


def _resolve_api_key_settings(provider: Any) -> tuple[str, bool, str, str, str]:
    """Resolve API-key provider transport settings.

    Returns:
      (api_base_url, require_auth, key_env, header_name, auth_scheme)
    """
    api_base_url = ""
    require_auth = True
    key_env = ""
    header_name = "Authorization"
    auth_scheme = "Bearer"

    if provider.credentials and provider.credentials.api_key:
        creds = provider.credentials.api_key
        api_base_url = creds.api_base_url
        require_auth = creds.require_auth
        key_env = creds.api_key_env or ""
        header_name = creds.header_name or "Authorization"
        auth_scheme = creds.auth_scheme or "Bearer"
    elif provider.api_key_config:
        cfg = provider.api_key_config
        api_base_url = cfg.get("api_base_url", "")
        require_auth = cfg.get("require_auth", True)
        key_env = cfg.get("api_key_env", "")
        header_name = cfg.get("header_name", "Authorization")
        auth_scheme = cfg.get("auth_scheme", "Bearer")
    else:
        api_base_url = provider.api_base_url or ""
        require_auth = True

    if not api_base_url:
        api_base_url = _default_api_base_url(provider)
    if not key_env:
        if getattr(provider, "id", "") == "openai":
            key_env = "OPENAI_API_KEY"
        else:
            key_env = "ANTHROPIC_API_KEY"
    return api_base_url, require_auth, key_env, header_name, auth_scheme


def _build_api_key_headers(provider: Any, require_auth: bool, key_env: str, header_name: str, auth_scheme: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not require_auth:
        return headers

    key = ""
    if provider.credentials and provider.credentials.api_key:
        key = str(getattr(provider.credentials.api_key, "api_key", "") or "").strip()
    if not key:
        key = os.environ.get(key_env, "").strip()
    if not key:
        # brain_agentctl auth login for api_key providers stores secrets here.
        try:
            token_path = os.path.expanduser(
                f"~/.local/share/brain_agent_proxy/tokens/{provider.id}_api_key.json"
            )
            if os.path.exists(token_path):
                with open(token_path) as f:
                    token_data = json.load(f) or {}
                token_key = str(token_data.get("api_key", "") or "").strip()
                if token_key:
                    key = token_key
        except Exception:
            pass
    if not key and getattr(provider, "id", "") == "openai":
        # Reuse Codex login credential if available.
        try:
            auth_path = os.path.expanduser("~/.codex/auth.json")
            if os.path.exists(auth_path):
                with open(auth_path) as f:
                    auth_data = json.load(f)
                codex_key = str(auth_data.get("OPENAI_API_KEY", "")).strip()
                if codex_key and codex_key.lower() != "none":
                    key = codex_key
        except Exception:
            pass
    if not key and getattr(provider, "oauth_config", None):
        # Optional OAuth Device fallback for providers like openai.
        oauth_cfg = provider.oauth_config or {}
        token_file = oauth_cfg.get("token_file")
        if token_file:
            try:
                with open(os.path.expanduser(token_file)) as f:
                    token_data = json.load(f)
                expires_at = int(token_data.get("expires_at", 0) or 0)
                access_token = str(token_data.get("access_token", "")).strip()
                if access_token and (expires_at == 0 or expires_at > int(time.time())):
                    key = access_token
            except Exception:
                pass
    if not key:
        raise ValueError(
            f"Missing upstream credential for provider {provider.id}: "
            f"set config.providers.{provider.id}.api_key.api_key or env {key_env} "
            f"or run 'brain_agentctl auth --provider {provider.id}'"
        )

    if header_name.lower() == "authorization":
        scheme = (auth_scheme or "Bearer").strip()
        headers["Authorization"] = f"{scheme} {key}" if scheme else key
    else:
        headers[header_name] = key
    return headers


def _minimax_chain(provider: Any) -> str:
    if getattr(provider, "id", "") != "minimax":
        return ""
    env_chain = os.environ.get("BRAIN_AGENT_PROXY_MINIMAX_CHAIN", "").strip().lower()
    if env_chain in {"native", "generic"}:
        return env_chain
    cfg = getattr(provider, "minimax_config", None) or {}
    configured = str(cfg.get("chain", "native") or "native").strip().lower()
    if configured in {"native", "generic"}:
        return configured
    return "native"


def _build_minimax_provider(provider: Any):
    from .providers.minimax import MiniMaxProvider

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    key = ""
    if provider.credentials and provider.credentials.api_key:
        key = str(getattr(provider.credentials.api_key, "api_key", "") or "").strip()
    cfg = getattr(provider, "minimax_config", None) or {}
    return MiniMaxProvider(
        provider_id=provider.id,
        api_key=key,
        api_key_env=key_env,
        api_base_url=api_base_url,
        api_root_url=str(cfg.get("api_root_url", "") or ""),
        header_name=header_name,
        auth_scheme=auth_scheme,
        require_auth=require_auth,
        strip_ignored_fields=bool(cfg.get("strip_ignored_fields", True)),
        validate_temperature=bool(cfg.get("validate_temperature", True)),
        reject_unsupported_content=bool(cfg.get("reject_unsupported_content", True)),
    )


def _apply_passthrough_anthropic_headers(headers: Dict[str, str], source_headers: Any | None) -> Dict[str, str]:
    """Forward Anthropic client headers that can affect upstream routing/billing."""
    if not source_headers:
        return headers

    for name in (
        "x-anthropic-billing-header",
        "anthropic-beta",
        "anthropic-dangerous-direct-browser-access",
    ):
        value = source_headers.get(name)
        if value:
            headers[name] = value
    return headers


def _resolve_fixed_provider(provider_id: str, api_key: Optional[str]) -> Any:
    config = get_config()
    routing_engine = RoutingEngine(config)
    provider = routing_engine._find_enabled_provider(provider_id)
    if not provider:
        raise ValueError(f"Provider '{provider_id}' not found or disabled")

    if not api_key:
        return provider

    client_provider, client_info = routing_engine.find_provider_by_client_key(api_key)
    if client_provider:
        bound = client_provider.id
    elif client_info:
        bound = str(client_info.provider or "").strip()
    else:
        parsed = routing_engine.parse_client_key(api_key)
        bound = str((parsed or {}).get("provider") or "").strip()

    if bound and bound != provider_id:
        raise ValueError(
            f"Provider mismatch: client key is bound to provider '{bound}', "
            f"but endpoint requires provider '{provider_id}'"
        )
    return provider


def _extract_client_key_from_ws(websocket: WebSocket) -> Optional[str]:
    authorization = websocket.headers.get("authorization")
    x_api_key = websocket.headers.get("x-api-key")
    return _extract_client_key(authorization, x_api_key)


def _build_minimax_ws_url(provider: Any, path: str) -> str:
    minimax = _build_minimax_provider(provider)
    root = minimax.get_api_root_url().rstrip("/")
    if root.startswith("https://"):
        root = "wss://" + root[len("https://"):]
    elif root.startswith("http://"):
        root = "ws://" + root[len("http://"):]
    return f"{root}{path}"


async def _forward_raw_api_key_post(
    provider: Any,
    path: str,
    body: Dict[str, Any],
    *,
    use_root_url: bool = False,
) -> Any:
    import httpx

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)
    base_url = api_base_url
    if provider.id == "minimax":
        minimax = _build_minimax_provider(provider)
        headers = minimax.build_headers()
        base_url = minimax.get_api_root_url() if use_root_url else minimax.get_api_base_url()

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{base_url}{path}", json=body, headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")

    content_type = str(resp.headers.get("content-type", "") or "").lower()
    if "json" in content_type:
        return _parse_json_response(resp)
    return Response(content=resp.content, media_type=resp.headers.get("content-type"))


async def _forward_raw_api_key_get(
    provider: Any,
    path: str,
    query: Dict[str, Any],
    *,
    use_root_url: bool = False,
) -> Any:
    import httpx

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)
    base_url = api_base_url
    if provider.id == "minimax":
        minimax = _build_minimax_provider(provider)
        headers = minimax.build_headers()
        base_url = minimax.get_api_root_url() if use_root_url else minimax.get_api_base_url()

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.get(f"{base_url}{path}", params=query, headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")

    content_type = str(resp.headers.get("content-type", "") or "").lower()
    if "json" in content_type:
        return _parse_json_response(resp)
    return Response(content=resp.content, media_type=resp.headers.get("content-type"))


async def _forward_raw_api_key_multipart(
    provider: Any,
    path: str,
    request: Request,
    *,
    use_root_url: bool = False,
) -> Any:
    import httpx

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)
    headers.pop("Content-Type", None)
    base_url = api_base_url
    if provider.id == "minimax":
        minimax = _build_minimax_provider(provider)
        headers = minimax.build_headers()
        headers.pop("Content-Type", None)
        base_url = minimax.get_api_root_url() if use_root_url else minimax.get_api_base_url()

    form = await request.form()
    data: list[tuple[str, Any]] = []
    files: list[tuple[str, tuple[str, bytes, str]]] = []

    items = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for key, value in items:
        if isinstance(value, UploadFile) or (
            hasattr(value, "filename") and hasattr(value, "file") and hasattr(value, "content_type")
        ):
            content = await value.read()
            files.append(
                (
                    key,
                    (
                        value.filename or "upload.bin",
                        content,
                        value.content_type or "application/octet-stream",
                    ),
                )
            )
        else:
            data.append((key, value))

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{base_url}{path}", data=data, files=files, headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")
    return _parse_json_response(resp)


async def _relay_minimax_websocket(client_ws: WebSocket, provider: Any, path: str) -> None:
    import websockets
    from websockets.exceptions import ConnectionClosed

    minimax = _build_minimax_provider(provider)
    headers = minimax.build_headers()
    upstream_url = _build_minimax_ws_url(provider, path)

    await client_ws.accept()

    async with websockets.connect(
        upstream_url,
        additional_headers=headers,
        open_timeout=30,
        close_timeout=10,
        max_size=None,
    ) as upstream_ws:
        async def client_to_upstream() -> None:
            while True:
                message = await client_ws.receive()
                msg_type = message.get("type")
                if msg_type == "websocket.disconnect":
                    try:
                        await upstream_ws.close()
                    except Exception:
                        pass
                    return
                if message.get("text") is not None:
                    await upstream_ws.send(message["text"])
                    continue
                if message.get("bytes") is not None:
                    await upstream_ws.send(message["bytes"])

        async def upstream_to_client() -> None:
            while True:
                payload = await upstream_ws.recv()
                if isinstance(payload, bytes):
                    await client_ws.send_bytes(payload)
                else:
                    await client_ws.send_text(payload)

        tasks = (
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        )
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, ConnectionClosed)):
                raise exc


def _ensure_kimi_system_blocks(payload: Dict[str, Any]) -> Dict[str, Any]:
    system = payload.get("system")
    if isinstance(system, str):
        system_blocks = [{"type": "text", "text": system}]
    elif isinstance(system, list):
        system_blocks = [item for item in system if isinstance(item, dict)]
    else:
        system_blocks = []

    if not system_blocks:
        try:
            with open(KIMI_SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
                template = json.load(f)
            if isinstance(template, list) and template:
                payload["system"] = copy.deepcopy(template)
                return payload
        except Exception:
            pass

    billing_text = f"x-anthropic-billing-header: {KIMI_DEFAULT_BILLING_HEADER}"
    if not any(billing_text in str(block.get("text", "")) for block in system_blocks):
        system_blocks.insert(0, {"type": "text", "text": billing_text})

    sdk_text = "You are a Claude agent, built on Anthropic's Claude Agent SDK."
    if not any(sdk_text == str(block.get("text", "")) for block in system_blocks):
        system_blocks.append(
            {
                "type": "text",
                "text": sdk_text,
                "cache_control": {"type": "ephemeral"},
            }
        )

    payload["system"] = system_blocks
    return payload


def _apply_kimi_upstream_shape(
    payload: Dict[str, Any],
    headers: Dict[str, str],
    source_headers: Any | None,
) -> tuple[Dict[str, Any], Dict[str, str]]:
    payload = _ensure_kimi_system_blocks(payload)

    headers["anthropic-beta"] = KIMI_DEFAULT_BETAS
    headers["User-Agent"] = KIMI_DEFAULT_USER_AGENT
    headers["x-app"] = "cli"

    if source_headers:
        for name in (
            "x-stainless-arch",
            "x-stainless-lang",
            "x-stainless-os",
            "x-stainless-package-version",
            "x-stainless-retry-count",
            "x-stainless-runtime",
            "x-stainless-runtime-version",
            "x-stainless-timeout",
            "accept-language",
            "sec-fetch-mode",
        ):
            value = source_headers.get(name)
            if value:
                headers[name] = value

    headers.setdefault("x-stainless-arch", "x64")
    headers.setdefault("x-stainless-lang", "js")
    headers.setdefault("x-stainless-os", "Linux")
    headers.setdefault("x-stainless-package-version", "0.74.0")
    headers.setdefault("x-stainless-retry-count", "0")
    headers.setdefault("x-stainless-runtime", "node")
    headers.setdefault("x-stainless-runtime-version", "v24.14.0")
    headers.setdefault("x-stainless-timeout", "600")
    return payload, headers


def _resolve_provider_secret(
    provider: Any,
    default_env: str,
) -> tuple[str, str, str]:
    """Resolve provider secret and transport hints.

    Returns:
      (api_key, api_key_env, api_base_url)
    """
    api_key = ""
    api_key_env = default_env
    api_base_url = ""

    if provider.credentials and provider.credentials.api_key:
        creds = provider.credentials.api_key
        api_key = str(getattr(creds, "api_key", "") or "").strip()
        api_key_env = str(getattr(creds, "api_key_env", "") or "").strip() or default_env
        api_base_url = str(getattr(creds, "api_base_url", "") or "").strip()
    elif provider.api_key_config:
        cfg = provider.api_key_config
        api_key = str(cfg.get("api_key", "") or "").strip()
        api_key_env = str(cfg.get("api_key_env", "") or "").strip() or default_env
        api_base_url = str(cfg.get("api_base_url", "") or "").strip()
    else:
        api_base_url = str(getattr(provider, "api_base_url", "") or "").strip()

    if not api_key:
        api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        # Optional token-file fallback for api_key providers.
        try:
            token_path = os.path.expanduser(
                f"~/.local/share/brain_agent_proxy/tokens/{provider.id}_api_key.json"
            )
            if os.path.exists(token_path):
                with open(token_path) as f:
                    token_data = json.load(f) or {}
                token_key = str(token_data.get("api_key", "") or "").strip()
                if token_key:
                    api_key = token_key
        except Exception:
            pass
    return api_key, api_key_env, api_base_url


def _estimate_input_tokens_from_messages(body: Dict[str, Any]) -> int:
    """Estimate input tokens for Anthropic count_tokens compatibility.

    We use a deterministic approximation to avoid 404s from unsupported endpoint.
    """
    text_parts = []

    for msg in body.get("messages", []):
        role = str(msg.get("role", ""))
        text_parts.append(role)
        text_parts.append(_normalize_content(msg.get("content", "")))

    system = body.get("system")
    if system is not None:
        text_parts.append(_normalize_content(system))

    combined = " ".join(p for p in text_parts if p)
    if not combined:
        return 0

    # Rough approximation: ~4 chars per token for mixed CJK/Latin payloads.
    return max(1, (len(combined) + 3) // 4)


def _estimate_tool_tokens_from_messages(body: Dict[str, Any]) -> int:
    tools = body.get("tools") or []
    if not isinstance(tools, list) or not tools:
        return 0
    try:
        packed = json.dumps(tools, ensure_ascii=False)
    except Exception:
        return 0
    return max(0, len(packed) // 4)


def _estimate_output_tokens_from_messages(body: Dict[str, Any]) -> int:
    """Approximate assistant output budget for copilot-api parity."""
    max_tokens = body.get("max_tokens")
    try:
        value = int(max_tokens) if max_tokens is not None else 0
    except Exception:
        value = 0
    return max(0, value)


def _parse_json_response(resp: Any) -> Dict[str, Any]:
    """Parse provider response JSON with actionable error details."""
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        snippet = (resp.text or "")[:200].strip()
        if not snippet:
            snippet = "<empty body>"
        raise ValueError(
            f"Provider returned non-JSON response (status={resp.status_code}): {snippet}"
        ) from e


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan."""
    # Startup
    config = get_config()
    print(f"[brain_agent_proxy] Starting on {config.host}:{config.port}")
    print(f"[brain_agent_proxy] Loaded {len(config.providers)} providers")

    # Register to IPC daemon
    if register_service():
        print(f"[brain_agent_proxy] Registered to IPC: {SERVICE_NAME}")
        start_heartbeat_thread(interval=30)
        print(f"[brain_agent_proxy] Heartbeat thread started")
    else:
        print(f"[brain_agent_proxy] Warning: Failed to register to IPC")

    yield

    # Shutdown
    print("[brain_agent_proxy] Shutting down")


app = FastAPI(
    title="brain_agent_proxy",
    description="Unified proxy for Claude Code, Codex, and AI providers",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return Response(content="Server running", media_type="text/plain")


def _request_receive_with_body(body: bytes):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _get_trace_record(request: Request) -> Optional[dict[str, Any]]:
    return getattr(request.state, "proxy_trace_record", None)


def _mask_client_key(client_key: str) -> str:
    if not client_key:
        return ""
    if len(client_key) <= 16:
        return client_key
    return f"{client_key[:10]}...{client_key[-6:]}"


def _coerce_request_preview(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _build_request_trace_record(
    *,
    request: Request,
    body: bytes,
    client_key: str,
) -> dict[str, Any]:
    body_data = _coerce_request_preview(body)
    model = str(body_data.get("model", "") or "")
    stream = bool(body_data.get("stream", False))
    messages = body_data.get("messages")
    input_items = body_data.get("input")

    provider_hint = ""
    selected_model = model
    if "/" in model:
        provider_hint, _, selected_model = model.partition("/")

    token_provider = ""
    token_model = ""
    token_name = ""
    if client_key:
        parsed = RoutingEngine(get_config()).parse_client_key(client_key)
        if parsed:
            token_provider = str(parsed.get("provider", "") or "")
            token_model = str(parsed.get("model", "") or "")
            token_name = str(parsed.get("name", "") or "")

    return {
        "id": 0,
        "created_at": datetime.now().isoformat(),
        "method": request.method,
        "path": request.url.path,
        "query": str(request.url.query or ""),
        "state": "started",
        "status_code": None,
        "duration_ms": None,
        "stream": stream,
        "model": model,
        "selected_model": selected_model,
        "provider_hint": provider_hint,
        "token_provider": token_provider,
        "token_model": token_model,
        "token_name": token_name,
        "client_key": _mask_client_key(client_key),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "input_count": len(input_items) if isinstance(input_items, list) else 0,
        "body_bytes": len(body),
        "error": "",
        "chunks": 0,
        "response_class": "",
        "bridge_entered": False,
        "bridge_raw_chunks": 0,
        "bridge_raw_bytes": 0,
        "bridge_sse_events": 0,
        "bridge_event_types": [],
        "bridge_parse_errors": 0,
        "_started_monotonic": time.perf_counter(),
    }


async def _append_recent_request(record: dict[str, Any]) -> dict[str, Any]:
    global _recent_request_seq
    async with _recent_requests_lock:
        _recent_request_seq += 1
        record["id"] = _recent_request_seq
        _recent_requests.append(record)
    return record


async def _finish_recent_request(
    record: dict[str, Any],
    *,
    state: str,
    status_code: Optional[int] = None,
    error: str = "",
    chunks: Optional[int] = None,
) -> None:
    duration_ms = round((time.perf_counter() - record["_started_monotonic"]) * 1000, 2)
    async with _recent_requests_lock:
        record["state"] = state
        if status_code is not None:
            record["status_code"] = status_code
        record["duration_ms"] = duration_ms
        if error:
            record["error"] = error[:500]
        if chunks is not None:
            record["chunks"] = chunks


def _public_request_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


async def _wrap_stream_with_trace(body_iterator: Any, record: dict[str, Any], status_code: int):
    chunk_count = 0
    try:
        async for chunk in body_iterator:
            if chunk:
                chunk_count += 1
            yield chunk
        await _finish_recent_request(
            record,
            state="stream_completed",
            status_code=status_code,
            chunks=chunk_count,
        )
    except Exception as exc:
        await _finish_recent_request(
            record,
            state="stream_error",
            status_code=status_code,
            error=str(exc),
            chunks=chunk_count,
        )
        raise


@app.middleware("http")
async def trace_recent_requests(request: Request, call_next):
    if request.method.upper() != "POST" or request.url.path not in TRACEABLE_PATHS:
        return await call_next(request)

    body = await request.body()
    cloned_request = Request(request.scope, _request_receive_with_body(body))
    client_key = _extract_client_key(
        request.headers.get("authorization"),
        request.headers.get("x-api-key"),
    )
    record = await _append_recent_request(
        _build_request_trace_record(request=request, body=body, client_key=client_key)
    )
    cloned_request.state.proxy_trace_record = record

    try:
        response = await call_next(cloned_request)
    except Exception as exc:
        await _finish_recent_request(record, state="error", status_code=500, error=str(exc))
        raise

    record["response_class"] = response.__class__.__name__
    if isinstance(response, StreamingResponse):
        response.body_iterator = _wrap_stream_with_trace(response.body_iterator, record, response.status_code)
    else:
        await _finish_recent_request(record, state="completed", status_code=response.status_code)

    response.headers["x-brain-proxy-trace-id"] = str(record["id"])
    return response


def _sse(event: str, payload: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _chunk_has_visible_output(chunk: bytes) -> bool:
    if not chunk:
        return False
    return (
        b"text_delta" in chunk
        or b"tool_use" in chunk
        or b"input_json_delta" in chunk
    )


def _display_model(model: str, provider_id: Optional[str]) -> str:
    """Return model name with provider prefix for display, e.g. bytedance/doubao-seed-2-0-pro."""
    if not provider_id or "/" in model:
        return model
    return f"{provider_id}/{model}"


async def _passthrough_inject_context_window(stream_iter, model: str, provider_id: Optional[str] = None):
    """Inject context_window into message_start for direct-passthrough SSE streams."""
    cw = get_context_window(model, provider_id)
    display = _display_model(model, provider_id)
    has_text = False
    saw_tool_use = False
    max_block_index = -1
    buffered_tail: list[bytes] = []

    async for chunk in stream_iter:
        if b"text_delta" in chunk:
            has_text = True
        if b"tool_use" in chunk or b"input_json_delta" in chunk:
            saw_tool_use = True

        if b"content_block_start" in chunk:
            try:
                for line in chunk.decode("utf-8").split("\n"):
                    if line.startswith("data:"):
                        d = json.loads(line[5:].strip())
                        if d.get("type") == "content_block_start":
                            max_block_index = max(max_block_index, d.get("index", 0))
            except Exception:
                pass

        if b"message_start" in chunk:
            try:
                text = chunk.decode("utf-8")
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    if line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                        if data.get("type") == "message_start":
                            msg = data.setdefault("message", {})
                            if cw is not None:
                                msg.setdefault("usage", {}).setdefault("context_window", cw)
                            msg["model"] = display
                            lines[i] = "data: " + json.dumps(data, ensure_ascii=False)
                            chunk = "\n".join(lines).encode("utf-8")
                        break
            except Exception:
                pass

        if b"message_stop" in chunk or b"message_delta" in chunk:
            buffered_tail.append(chunk)
        else:
            for b in buffered_tail:
                yield b
            buffered_tail.clear()
            yield chunk

    if not has_text and not saw_tool_use:
        inject_index = max_block_index + 1
        yield _sse("content_block_start", {"type": "content_block_start", "index": inject_index, "content_block": {"type": "text", "text": ""}})
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": inject_index, "delta": {"type": "text_delta", "text": "(上游返回空响应，请重试)"}})
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": inject_index})

    for b in buffered_tail:
        yield b


def _format_stream_error_text(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    message = re.sub(r"\s+", " ", message)
    if len(message) > 400:
        message = f"{message[:397]}..."
    return f"Upstream stream error: {message}"


async def _anthropic_message_to_sse(message: Dict[str, Any], provider_id: Optional[str] = None):
    """Convert one Anthropic message response to SSE event stream."""
    usage = message.get("usage", {}) or {}
    model = _display_model(message.get("model", ""), provider_id)
    msg_id = message.get("id", f"msg_{uuid.uuid4().hex[:8]}")
    content = message.get("content", []) or []

    _msg_start_usage: Dict[str, Any] = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": 0,
    }
    _ctx_win = get_context_window(model, provider_id)
    if _ctx_win is not None:
        _msg_start_usage["context_window"] = _ctx_win
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "usage": _msg_start_usage,
        },
    })

    for idx, block in enumerate(content):
        btype = block.get("type")
        if btype == "text":
            yield _sse("content_block_start", {
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "text", "text": ""},
            })
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": idx,
                "delta": {"type": "text_delta", "text": block.get("text", "")},
            })
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": idx})
        elif btype == "tool_use":
            tool_id = block.get("id", f"toolu_{uuid.uuid4().hex[:8]}")
            tool_name = block.get("name", "")
            tool_input = block.get("input", {}) or {}
            yield _sse("content_block_start", {
                "type": "content_block_start",
                "index": idx,
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": {},
                },
            })
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": idx,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(tool_input, ensure_ascii=False),
                },
            })
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": idx})

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": message.get("stop_reason", "end_turn"), "stop_sequence": None},
        "usage": {"output_tokens": usage.get("output_tokens", 0)},
    })
    yield _sse("message_stop", {"type": "message_stop"})


async def _collect_anthropic_sse_to_message(raw_iter, fallback_model: str) -> Dict[str, Any]:
    """Collect Anthropic SSE events into one non-stream message response."""
    buffer = ""
    message: Dict[str, Any] = {
        "id": f"msg_{uuid.uuid4().hex[:8]}",
        "type": "message",
        "role": "assistant",
        "model": fallback_model,
        "content": [],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    blocks: Dict[int, Dict[str, Any]] = {}
    tool_json_parts: Dict[int, str] = {}

    async for chunk in raw_iter:
        part = chunk.decode("utf-8", "ignore").replace("\r\n", "\n")
        buffer += part

        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            data_lines = []
            for ln in event.splitlines():
                if ln.startswith("data:"):
                    data_lines.append(ln[5:].lstrip())
            if not data_lines:
                continue
            data = "\n".join(data_lines).strip()
            if not data or data == "[DONE]":
                continue

            try:
                obj = json.loads(data)
            except Exception:
                continue

            etype = str(obj.get("type", "") or "")
            if etype == "message_start":
                msg = obj.get("message", {}) or {}
                message["id"] = msg.get("id", message["id"])
                message["model"] = msg.get("model", message["model"])
                if isinstance(msg.get("usage"), dict):
                    message["usage"].update(msg["usage"])
            elif etype == "content_block_start":
                idx = int(obj.get("index", 0) or 0)
                block = obj.get("content_block", {}) or {}
                btype = str(block.get("type", "") or "")
                if btype == "text":
                    blocks[idx] = {"type": "text", "text": ""}
                elif btype == "tool_use":
                    blocks[idx] = {
                        "type": "tool_use",
                        "id": block.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                        "name": block.get("name", ""),
                        "input": {},
                    }
                    tool_json_parts[idx] = ""
            elif etype == "content_block_delta":
                idx = int(obj.get("index", 0) or 0)
                delta = obj.get("delta", {}) or {}
                if delta.get("type") == "text_delta" and idx in blocks:
                    blocks[idx]["text"] = blocks[idx].get("text", "") + str(delta.get("text", "") or "")
                elif delta.get("type") == "input_json_delta" and idx in blocks:
                    tool_json_parts[idx] = tool_json_parts.get(idx, "") + str(delta.get("partial_json", "") or "")
            elif etype == "content_block_stop":
                idx = int(obj.get("index", 0) or 0)
                block = blocks.get(idx)
                if not block:
                    continue
                if block.get("type") == "tool_use":
                    raw_json = tool_json_parts.get(idx, "").strip()
                    if raw_json:
                        try:
                            parsed = json.loads(raw_json)
                            if isinstance(parsed, dict):
                                block["input"] = parsed
                        except Exception:
                            pass
                message["content"].append(block)
                blocks.pop(idx, None)
                tool_json_parts.pop(idx, None)
            elif etype == "message_delta":
                delta = obj.get("delta", {}) or {}
                if delta.get("stop_reason"):
                    message["stop_reason"] = delta["stop_reason"]
                if isinstance(obj.get("usage"), dict):
                    message["usage"].update(obj["usage"])
            elif etype == "message_stop":
                return message

    for idx in sorted(blocks):
        message["content"].append(blocks[idx])
    return message


async def _openai_sse_to_anthropic_sse(
    raw_iter,
    trace_record: Optional[dict[str, Any]] = None,
    estimated_input_tokens: int = 0,
    provider_id: Optional[str] = None,
):
    """Translate OpenAI chat-completions SSE stream into Anthropic messages SSE."""
    buffer = ""
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    model = ""
    started = False
    stopped = False
    next_block_index = 0
    text_block_index = None
    tool_blocks: Dict[str, Dict[str, Any]] = {}
    stream_error: Optional[Exception] = None
    raw_chunk_count = 0
    raw_bytes = 0
    sse_event_count = 0
    saw_tool_use = False

    def _trace_event() -> None:
        nonlocal sse_event_count
        sse_event_count += 1
        if trace_record is not None:
            trace_record["bridge_sse_events"] = sse_event_count

    def _trace_event_type(event_type: str) -> None:
        if trace_record is None:
            return
        event_types = trace_record.setdefault("bridge_event_types", [])
        if len(event_types) < 20:
            event_types.append(event_type)

    async def _close_tool_block(key: str) -> None:
        info = tool_blocks.pop(key, None)
        if info is None:
            return
        _trace_event()
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})

    if trace_record is not None:
        trace_record["bridge_entered"] = True

    async def _emit_message_start(input_tokens: int = 0):
        nonlocal started
        if started:
            return
        started = True
        _usage: Dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": 0}
        _cw = get_context_window(model, provider_id)
        if _cw is not None:
            _usage["context_window"] = _cw
        return _sse("message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "usage": _usage,
            },
        })

    def _map_stop_reason(reason: Optional[str]) -> str:
        m = {
            "stop": "end_turn",
            "length": "max_tokens",
            "content_filter": "stop_sequence",
            "tool_calls": "tool_use",
        }
        return m.get((reason or "").lower(), "end_turn")

    try:
        async for chunk in raw_iter:
            raw_chunk_count += 1
            raw_bytes += len(chunk or b"")
            if trace_record is not None:
                trace_record["bridge_raw_chunks"] = raw_chunk_count
                trace_record["bridge_raw_bytes"] = raw_bytes
            part = chunk.decode("utf-8", "ignore")
            # OpenAI/Codex streams may use CRLF; normalize for robust SSE framing.
            part = part.replace("\r\n", "\n")
            buffer += part

            while "\n\n" in buffer:
                event, buffer = buffer.split("\n\n", 1)
                data_lines = []
                for ln in event.splitlines():
                    if ln.startswith("data:"):
                        data_lines.append(ln[5:].lstrip())
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data:
                    continue
                if data == "[DONE]":
                    _trace_event_type("[DONE]")
                    if stopped:
                        continue
                    if text_block_index is not None:
                        _trace_event()
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                        text_block_index = None
                    for info in list(tool_blocks.values()):
                        _trace_event()
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})
                    tool_blocks.clear()
                    _trace_event()
                    yield _sse("message_delta", {
                        "type": "message_delta",
                        "delta": {"stop_reason": "tool_use" if saw_tool_use else "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 0},
                    })
                    _trace_event()
                    yield _sse("message_stop", {"type": "message_stop"})
                    stopped = True
                    continue

                try:
                    obj = json.loads(data)
                except Exception:
                    if trace_record is not None:
                        trace_record["bridge_parse_errors"] = int(
                            trace_record.get("bridge_parse_errors", 0)
                        ) + 1
                    continue

                if obj.get("id"):
                    message_id = obj.get("id")
                if obj.get("model"):
                    model = _display_model(obj.get("model"), provider_id)

                event_type = str(obj.get("type", "") or "")
                _trace_event_type(event_type or "<missing>")
                if event_type:
                    if event_type == "response.created":
                        response_obj = obj.get("response", {}) or {}
                        if response_obj.get("id"):
                            message_id = response_obj.get("id")
                        if response_obj.get("model"):
                            model = _display_model(response_obj.get("model"), provider_id)
                        if not started:
                            evt = await _emit_message_start(max(0, estimated_input_tokens))
                            if evt:
                                _trace_event()
                                yield evt
                        continue
                    if event_type == "response.output_text.delta":
                        if not started:
                            evt = await _emit_message_start(max(0, estimated_input_tokens))
                            if evt:
                                _trace_event()
                                yield evt
                        text = obj.get("delta")
                        if isinstance(text, str) and text:
                            if text_block_index is None:
                                text_block_index = next_block_index
                                next_block_index += 1
                                _trace_event()
                                yield _sse("content_block_start", {
                                    "type": "content_block_start",
                                    "index": text_block_index,
                                    "content_block": {"type": "text", "text": ""},
                                })
                            _trace_event()
                            yield _sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": text_block_index,
                                "delta": {"type": "text_delta", "text": text},
                            })
                        continue
                    if event_type == "response.output_item.added":
                        item = obj.get("item", {}) or {}
                        if str(item.get("type", "") or "") != "function_call":
                            continue
                        if not started:
                            evt = await _emit_message_start(max(0, estimated_input_tokens))
                            if evt:
                                _trace_event()
                                yield evt
                        if text_block_index is not None:
                            _trace_event()
                            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                            text_block_index = None
                        item_id = str(item.get("id", "") or "")
                        tool_name = str(item.get("name", "") or "")
                        if not item_id or not tool_name:
                            continue
                        tool_call_id = str(item.get("call_id", "") or item_id)
                        if item_id not in tool_blocks:
                            tool_blocks[item_id] = {
                                "anthropic_index": next_block_index,
                                "id": tool_call_id,
                                "name": tool_name,
                            }
                            next_block_index += 1
                            saw_tool_use = True
                            _trace_event()
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": tool_blocks[item_id]["anthropic_index"],
                                "content_block": {
                                    "type": "tool_use",
                                    "id": tool_blocks[item_id]["id"],
                                    "name": tool_blocks[item_id]["name"],
                                    "input": {},
                                },
                            })
                        continue
                    if event_type == "response.function_call_arguments.delta":
                        item_id = str(obj.get("item_id", "") or "")
                        info = tool_blocks.get(item_id)
                        args_delta = obj.get("delta")
                        if info and isinstance(args_delta, str) and args_delta:
                            _trace_event()
                            yield _sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": info["anthropic_index"],
                                "delta": {"type": "input_json_delta", "partial_json": args_delta},
                            })
                        continue
                    if event_type == "response.output_item.done":
                        item = obj.get("item", {}) or {}
                        if str(item.get("type", "") or "") != "function_call":
                            continue
                        item_id = str(item.get("id", "") or "")
                        if item_id in tool_blocks:
                            async for tool_chunk in _close_tool_block(item_id):
                                yield tool_chunk
                        continue
                    if event_type == "response.completed":
                        response_obj = obj.get("response", {}) or {}
                        usage_obj = response_obj.get("usage", {}) or {}
                        if not started:
                            evt = await _emit_message_start(
                                max(int(usage_obj.get("input_tokens", 0) or 0), estimated_input_tokens)
                            )
                            if evt:
                                _trace_event()
                                yield evt
                        if text_block_index is not None:
                            _trace_event()
                            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                            text_block_index = None
                        for key in list(tool_blocks):
                            async for tool_chunk in _close_tool_block(key):
                                yield tool_chunk
                        if not stopped:
                            _trace_event()
                            yield _sse("message_delta", {
                                "type": "message_delta",
                                "delta": {"stop_reason": "tool_use" if saw_tool_use else "end_turn", "stop_sequence": None},
                                "usage": {"output_tokens": usage_obj.get("output_tokens", 0)},
                            })
                            _trace_event()
                            yield _sse("message_stop", {"type": "message_stop"})
                            stopped = True
                        continue

                usage = obj.get("usage", {}) or {}
                prompt_tokens = usage.get("prompt_tokens", 0)
                cached_tokens = (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
                if not started:
                    _real = max(0, prompt_tokens - cached_tokens)
                    evt = await _emit_message_start(_real if _real > 0 else estimated_input_tokens)
                    if evt:
                        _trace_event()
                        yield evt

                choices = obj.get("choices") or []
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {}) or {}

                text = delta.get("content")
                if isinstance(text, str) and text:
                    if text_block_index is None:
                        text_block_index = next_block_index
                        next_block_index += 1
                        _trace_event()
                        yield _sse("content_block_start", {
                            "type": "content_block_start",
                            "index": text_block_index,
                            "content_block": {"type": "text", "text": ""},
                        })
                    _trace_event()
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": text_block_index,
                        "delta": {"type": "text_delta", "text": text},
                    })

                for tc in (delta.get("tool_calls") or []):
                    tc_index = tc.get("index")
                    if tc_index is None:
                        continue
                    info = tool_blocks.get(str(tc_index))

                    tc_id = tc.get("id")
                    fn = tc.get("function", {}) or {}
                    fn_name = fn.get("name")
                    args_delta = fn.get("arguments", "")

                    if info is None and tc_id and fn_name:
                        if text_block_index is not None:
                            _trace_event()
                            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                            text_block_index = None
                        info = {
                            "anthropic_index": next_block_index,
                            "id": tc_id,
                            "name": fn_name,
                        }
                        next_block_index += 1
                        tool_blocks[str(tc_index)] = info
                        saw_tool_use = True
                        _trace_event()
                        yield _sse("content_block_start", {
                            "type": "content_block_start",
                            "index": info["anthropic_index"],
                            "content_block": {
                                "type": "tool_use",
                                "id": info["id"],
                                "name": info["name"],
                                "input": {},
                            },
                        })

                    if info and isinstance(args_delta, str) and args_delta:
                        _trace_event()
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": info["anthropic_index"],
                            "delta": {"type": "input_json_delta", "partial_json": args_delta},
                        })

                finish_reason = choice.get("finish_reason")
                if finish_reason is not None and not stopped:
                    if text_block_index is not None:
                        _trace_event()
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                        text_block_index = None
                    for key in list(tool_blocks):
                        async for tool_chunk in _close_tool_block(key):
                            yield tool_chunk

                    completion_tokens = usage.get("completion_tokens", 0)
                    _trace_event()
                    yield _sse("message_delta", {
                        "type": "message_delta",
                        "delta": {"stop_reason": _map_stop_reason(finish_reason), "stop_sequence": None},
                        "usage": {"output_tokens": completion_tokens},
                    })
                    _trace_event()
                    yield _sse("message_stop", {"type": "message_stop"})
                    stopped = True
    except Exception as exc:
        stream_error = exc
        print(f"[brain_agent_proxy] stream bridge error: {exc}")

    if stream_error is not None and not stopped:
        if not started:
            evt = await _emit_message_start(max(0, estimated_input_tokens))
            if evt:
                _trace_event()
                yield evt
            text_block_index = next_block_index
            next_block_index += 1
            _trace_event()
            yield _sse("content_block_start", {
                "type": "content_block_start",
                "index": text_block_index,
                "content_block": {"type": "text", "text": ""},
            })
            _trace_event()
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": text_block_index,
                "delta": {"type": "text_delta", "text": _format_stream_error_text(stream_error)},
            })
        if text_block_index is not None:
            _trace_event()
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
            text_block_index = None
        for key in list(tool_blocks):
            async for tool_chunk in _close_tool_block(key):
                yield tool_chunk
        _trace_event()
        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use" if saw_tool_use else "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        })
        _trace_event()
        yield _sse("message_stop", {"type": "message_stop"})
        stopped = True

    # Upstream stream may close without [DONE]/finish event.
    if not stopped:
        if not started:
            evt = await _emit_message_start(max(0, estimated_input_tokens))
            if evt:
                _trace_event()
                yield evt
        if text_block_index is not None:
            _trace_event()
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
            text_block_index = None
        for info in list(tool_blocks.values()):
            _trace_event()
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})
        tool_blocks.clear()
        _trace_event()
        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        })
        _trace_event()
        yield _sse("message_stop", {"type": "message_stop"})


@app.get("/health")
async def health():
    """Health check endpoint."""
    return await HealthChecker.check()


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """List available models - 动态从 Copilot API 获取."""
    # Simple API key check
    if authorization:
        if authorization.startswith("Bearer "):
            key = authorization[7:]
            # Allow any key if "*" is in ALLOWED_API_KEYS
            if "*" not in ALLOWED_API_KEYS and key not in ALLOWED_API_KEYS:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid API key"},
                )
        else:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid API key"},
            )

    config = get_config()
    models = []
    seen_model_ids: set[str] = set()

    def _append_unique_entries(**kwargs: Any) -> None:
        staged: list[Dict[str, Any]] = []
        _append_model_entries(staged, **kwargs)
        for entry in staged:
            model_id = str(entry.get("id", "") or "")
            if not model_id or model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            models.append(entry)

    # 尝试从 Copilot API 动态获取模型列表
    copilot_models = await _get_copilot_models()
    if copilot_models:
        for m in copilot_models:
            _append_unique_entries(
                model_id=m["id"],
                provider_id="copilot",
                provider_type="oauth",
                cli_type="chat_completions",
                capabilities=["code", "chat", "reasoning", "fast"],
                name=m.get("name", ""),
                vendor=m.get("vendor", ""),
            )

    # 追加静态 provider 配置，确保 proxy /v1/models 对所有 provider 一致可见。
    for provider in config.providers:
        if not provider.enabled:
            continue
        for model in provider.models:
            _append_unique_entries(
                model_id=model.id,
                provider_id=provider.id,
                provider_type=provider.type,
                cli_type=getattr(provider, "cli_type", "chat_completions"),
                capabilities=getattr(provider, "capabilities", []) or [],
                name=getattr(model, "name", "") or "",
                vendor=getattr(model, "vendor", "") or "",
            )

    return {
        "object": "list",
        "data": models,
    }


async def _get_copilot_models() -> list:
    """从 Copilot API 动态获取模型列表."""
    try:
        from .providers.github_copilot import GitHubCopilotProvider

        copilot = GitHubCopilotProvider()
        return await copilot.get_models()
    except Exception:
        return []


@app.post("/v1/messages")
async def handle_messages(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Handle Anthropic /v1/messages requests."""
    body = await request.json()
    handler = PROTOCOL_HANDLERS["messages"]

    api_key = _extract_client_key(authorization, x_api_key)

    try:
        await _enforce_request_policies("/v1/messages", body)
        normalized = handler.parse_request(body)
        if normalized.stream:
            trace_record = _get_trace_record(request)
            estimated_input_tokens = (
                _estimate_input_tokens_from_messages(body) + _estimate_tool_tokens_from_messages(body)
            )
            provider, _ = _resolve_provider(normalized, "messages", api_key)
            if provider.id == "copilot" and _copilot_prefers_native_messages(normalized.model):
                # Copilot native /v1/messages works for these model families, but the
                # upstream streaming endpoint can still reject otherwise valid requests.
                # Use a non-stream request and synthesize Anthropic SSE locally.
                non_stream_request = dict(normalized.original_request or {})
                non_stream_request["stream"] = False
                non_stream_normalized = normalized.model_copy(
                    update={"stream": False, "original_request": non_stream_request}
                )
                result = await route_and_forward(
                    non_stream_normalized,
                    "messages",
                    handler,
                    api_key,
                    source_headers=request.headers,
                )
                return StreamingResponse(_anthropic_message_to_sse(result, provider_id=provider.id), media_type="text/event-stream")
            stream_iter = await route_and_forward_stream(
                normalized,
                "messages",
                api_key,
                resolved_provider=provider,
                resolved_client_info=None,
                source_headers=request.headers,
            )
            if (
                (provider.type == "api_key" and _provider_supports_protocol(provider, "messages"))
                or provider.type == "claude_cli"
                or (provider.id == "copilot" and _copilot_prefers_native_messages(normalized.model))
            ):
                return StreamingResponse(
                    _passthrough_inject_context_window(stream_iter, normalized.model, provider_id=provider.id),
                    media_type="text/event-stream",
                )
            return StreamingResponse(
                _openai_sse_to_anthropic_sse(
                    stream_iter,
                    trace_record,
                    estimated_input_tokens=estimated_input_tokens,
                    provider_id=provider.id,
                ),
                media_type="text/event-stream",
            )
        result = await route_and_forward(normalized, "messages", handler, api_key, source_headers=request.headers)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content=handler.format_error(e),
        )


@app.post("/v1/messages/count_tokens")
async def handle_messages_count_tokens(request: Request, authorization: Optional[str] = Header(None)):
    """Handle Anthropic /v1/messages/count_tokens requests.

    Claude Code may call this endpoint before /v1/messages. We return a
    compatible response shape using local estimation.
    """
    _ = authorization  # Keep signature aligned with other endpoints.
    body = await request.json()
    anthropic_beta = request.headers.get("anthropic-beta", "")
    model = str(body.get("model", ""))
    input_tokens = _estimate_input_tokens_from_messages(body) + _estimate_tool_tokens_from_messages(body)
    output_tokens = _estimate_output_tokens_from_messages(body)

    # Align with copilot-api heuristics for Claude Code workloads.
    tools = body.get("tools") or []
    has_mcp_tool = isinstance(tools, list) and any(
        isinstance(t, dict) and str(t.get("name", "")).startswith("mcp__")
        for t in tools
    )
    if anthropic_beta.startswith("claude-code") and has_mcp_tool:
        pass
    else:
        if model.startswith("claude"):
            input_tokens += 346
        elif model.startswith("grok"):
            input_tokens += 480

    token_count = input_tokens
    if model.startswith("claude"):
        token_count = round(token_count * 1.15)
    elif model.startswith("grok"):
        token_count = round(token_count * 1.03)

    return {"input_tokens": max(1, token_count)}


@app.post("/v1/chat/completions")
async def handle_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Handle OpenAI /v1/chat/completions requests."""
    body = await request.json()
    handler = PROTOCOL_HANDLERS["chat_completions"]

    api_key = _extract_client_key(authorization, x_api_key)

    try:
        await _enforce_request_policies("/v1/chat/completions", body)
        normalized = handler.parse_request(body)
        if normalized.stream:
            stream_iter = await route_and_forward_stream(
                normalized,
                "chat_completions",
                api_key,
                source_headers=request.headers,
            )
            return StreamingResponse(stream_iter, media_type="text/event-stream")
        result = await route_and_forward(normalized, "chat_completions", handler, api_key, source_headers=request.headers)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content=handler.format_error(e),
        )


@app.post("/chat/completions")
async def handle_chat_completions_alias(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    return await handle_chat_completions(request, authorization, x_api_key)


@app.post("/v1/responses")
async def handle_responses(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Handle OpenAI /v1/responses requests."""
    body = await request.json()
    handler = PROTOCOL_HANDLERS["responses"]

    api_key = _extract_client_key(authorization, x_api_key)

    try:
        await _enforce_request_policies("/v1/responses", body)
        normalized = handler.parse_request(body)
        result = await route_and_forward(normalized, "responses", handler, api_key, source_headers=request.headers)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content=handler.format_error(e),
        )


@app.post("/v1/embeddings")
async def handle_embeddings(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Handle OpenAI /v1/embeddings requests."""
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)

    try:
        await _enforce_request_policies("/v1/embeddings", body)
        model = str(body.get("model", ""))
        if not model:
            raise ValueError("model is required for embeddings")
        result = await route_and_forward_embeddings(model=model, body=body, api_key=api_key)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "param": None,
                    "code": "internal_error",
                }
            },
        )


@app.post("/embeddings")
async def handle_embeddings_alias(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    return await handle_embeddings(request, authorization, x_api_key)


@app.post("/v1/image_generation")
async def handle_minimax_image_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/image_generation", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/t2a_v2")
async def handle_minimax_t2a_v2(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/t2a_v2", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/t2a_async_v2")
async def handle_minimax_t2a_async_v2(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/t2a_async_v2", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/get_voice")
async def handle_minimax_get_voice(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/get_voice", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/voice_clone")
async def handle_minimax_voice_clone(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_multipart(provider, "/v1/voice_clone", request, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/voice_design")
async def handle_minimax_voice_design(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/voice_design", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/delete_voice")
async def handle_minimax_delete_voice(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/delete_voice", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.get("/v1/query/t2a_async_v2")
async def handle_minimax_query_t2a_async_v2(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_get(
            provider,
            "/v1/query/t2a_async_v2",
            dict(request.query_params),
            use_root_url=True,
        )
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/video_generation")
async def handle_minimax_video_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/video_generation", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.get("/v1/query/video_generation")
async def handle_minimax_query_video_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_get(
            provider,
            "/v1/query/video_generation",
            dict(request.query_params),
            use_root_url=True,
        )
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/video_template_generation")
async def handle_minimax_video_template_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/video_template_generation", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.get("/v1/query/video_template_generation")
async def handle_minimax_query_video_template_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_get(
            provider,
            "/v1/query/video_template_generation",
            dict(request.query_params),
            use_root_url=True,
        )
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/music_generation")
async def handle_minimax_music_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/music_generation", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/lyrics_generation")
async def handle_minimax_lyrics_generation(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/lyrics_generation", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/files/upload")
async def handle_minimax_files_upload(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_multipart(provider, "/v1/files/upload", request, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.get("/v1/files/list")
async def handle_minimax_files_list(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_get(provider, "/v1/files/list", dict(request.query_params), use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.get("/v1/files/retrieve")
async def handle_minimax_files_retrieve(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_get(provider, "/v1/files/retrieve", dict(request.query_params), use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.post("/v1/files/delete")
async def handle_minimax_files_delete(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    body = await request.json()
    api_key = _extract_client_key(authorization, x_api_key)
    try:
        provider = _resolve_fixed_provider("minimax", api_key)
        return await _forward_raw_api_key_post(provider, "/v1/files/delete", body, use_root_url=True)
    except Exception as e:
        return JSONResponse(
            status_code=_status_code_for_exception(e),
            content={"error": {"type": "api_error", "message": str(e)}},
        )


@app.websocket("/ws/v1/t2a_v2")
async def handle_minimax_t2a_v2_ws(websocket: WebSocket):
    try:
        api_key = _extract_client_key_from_ws(websocket)
        provider = _resolve_fixed_provider("minimax", api_key)
        await _relay_minimax_websocket(websocket, provider, "/ws/v1/t2a_v2")
    except Exception as e:
        try:
            await websocket.accept()
            await websocket.send_json({"error": {"type": "api_error", "message": str(e)}})
        except Exception:
            pass
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


def _normalize_content(content: Any) -> str:
    """Normalize message content to string.

    Handles:
    - Plain string: "hello" -> "hello"
    - List format: [{"type": "text", "text": "hello"}] -> "hello"
    - Other: str(content)
    """
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        ctype = content.get("type")
        if ctype == "text":
            return str(content.get("text", ""))
        if ctype == "thinking":
            return str(content.get("thinking", ""))
        if ctype == "image":
            src = content.get("source", {}) or {}
            media_type = src.get("media_type", "")
            data = src.get("data", "")
            return f"[image:{media_type}:{len(str(data))}]"
        if ctype == "tool_result":
            return _normalize_content(content.get("content", ""))
        return _normalize_content(content.get("content", ""))
    elif isinstance(content, list):
        # Extract text from list of content blocks
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "ephemeral":
                continue
            part = _normalize_content(block)
            if part:
                parts.append(part)
        return " ".join(parts)
    else:
        return str(content)


def _build_openai_tools(normalized: Any) -> list[Dict[str, Any]]:
    """Convert normalized tools to OpenAI chat_completions tools format."""
    def _normalize_function_parameters(schema: Any) -> Dict[str, Any]:
        """Make tool schema compatible with OpenAI function parameters."""
        def _sanitize_required(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            out: list[str] = []
            for item in value:
                if isinstance(item, str):
                    if item:
                        out.append(item)
                    continue
                if isinstance(item, (list, tuple)):
                    for sub in item:
                        if isinstance(sub, str) and sub:
                            out.append(sub)
            # Keep order, remove duplicates.
            seen: set[str] = set()
            deduped: list[str] = []
            for name in out:
                if name in seen:
                    continue
                seen.add(name)
                deduped.append(name)
            return deduped

        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}

        normalized_schema = dict(schema)
        schema_type = normalized_schema.get("type")

        # OpenAI/Copilot is strict for function params:
        # object schema must include `properties`.
        if schema_type == "object" and "properties" not in normalized_schema:
            normalized_schema["properties"] = {}
        elif schema_type is None and "properties" not in normalized_schema:
            # Default unknown schema to a permissive object.
            normalized_schema["type"] = "object"
            normalized_schema["properties"] = {}

        if not isinstance(normalized_schema.get("properties"), dict):
            normalized_schema["properties"] = {}

        # Some MCP tool schemas may carry nested/invalid required shapes.
        # Upstream expects required to be a flat list[str].
        if "required" in normalized_schema:
            normalized_schema["required"] = _sanitize_required(normalized_schema.get("required"))

        return normalized_schema

    tools_data: list[Dict[str, Any]] = []
    for tool in getattr(normalized, "tools", []) or []:
        name = getattr(tool, "name", "") or ""
        if not name:
            continue
        description = getattr(tool, "description", "") or ""
        input_schema = _normalize_function_parameters(getattr(tool, "input_schema", {}) or {})
        tools_data.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": input_schema,
                },
            }
        )
    return tools_data


def _tool_name_limit_for_provider(provider: Any) -> int:
    """Return provider-specific tool name max length; 0 means unlimited."""
    pid = str(getattr(provider, "id", "") or "").lower()
    if pid in {"alibaba", "bytedance"}:
        return 64
    return 0


def _alias_tool_name(name: str, max_len: int) -> str:
    if max_len <= 0 or len(name) <= max_len:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    reserve = len("__") + len(digest)
    prefix_len = max(1, max_len - reserve)
    return f"{name[:prefix_len]}__{digest}"


def _rewrite_tool_names_for_provider(
    payload: Dict[str, Any],
    provider: Any,
) -> Dict[str, str]:
    """Rewrite too-long tool names in request payload; return alias->original map."""
    max_len = _tool_name_limit_for_provider(provider)
    if max_len <= 0:
        return {}

    alias_to_original: Dict[str, str] = {}
    original_to_alias: Dict[str, str] = {}

    def _rewrite_name(name: Any) -> Any:
        if not isinstance(name, str) or not name:
            return name
        alias = _alias_tool_name(name, max_len)
        if alias != name:
            alias_to_original[alias] = name
            original_to_alias[name] = alias
        return alias

    tools = payload.get("tools")
    if isinstance(tools, list):
        for t in tools:
            if not isinstance(t, dict):
                continue
            if isinstance(t.get("name"), str):
                t["name"] = _rewrite_name(t.get("name"))
                continue
            fn = t.get("function")
            if isinstance(fn, dict) and isinstance(fn.get("name"), str):
                fn["name"] = _rewrite_name(fn.get("name"))

    tc = payload.get("tool_choice")
    if isinstance(tc, dict):
        if tc.get("type") == "tool" and isinstance(tc.get("name"), str):
            tc_name = tc.get("name")
            if tc_name in original_to_alias:
                tc["name"] = original_to_alias[tc_name]
        elif tc.get("type") == "function":
            fn = tc.get("function")
            if isinstance(fn, dict) and isinstance(fn.get("name"), str):
                tc_name = fn.get("name")
                if tc_name in original_to_alias:
                    fn["name"] = original_to_alias[tc_name]

    return alias_to_original


def _restore_tool_names_in_response(result: Dict[str, Any], alias_to_original: Dict[str, str]) -> None:
    """Restore aliased tool names back to original names in non-stream response."""
    if not alias_to_original:
        return

    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if isinstance(name, str) and name in alias_to_original:
                    block["name"] = alias_to_original[name]

    choices = result.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message")
            if not isinstance(msg, dict):
                continue
            for tc in msg.get("tool_calls", []) or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function")
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                if isinstance(name, str) and name in alias_to_original:
                    fn["name"] = alias_to_original[name]


def _provider_supports_protocol(provider: Any, protocol: str) -> bool:
    protocols = set(getattr(provider, "protocols", []) or [])
    return protocol in protocols if protocols else False


THINKING_BUDGET_TOKENS = int(os.environ.get("BRAIN_AGENT_PROXY_THINKING_BUDGET_TOKENS", "30000") or 30000)


def _build_anthropic_messages_payload(normalized: Any, provider: Optional[Any] = None) -> Dict[str, Any]:
    """Build Anthropic messages payload while preserving original block structure."""
    payload = dict(getattr(normalized, "original_request", {}) or {})
    payload["model"] = _canonicalize_upstream_model(provider, normalized.model) if provider else normalized.model
    if "messages" not in payload:
        messages_data = []
        for m in normalized.messages:
            if hasattr(m, "role") and hasattr(m, "content"):
                messages_data.append({"role": m.role, "content": _normalize_content(m.content)})
            elif isinstance(m, dict):
                messages_data.append(
                    {"role": m.get("role", "user"), "content": _normalize_content(m.get("content", ""))}
                )
        payload["messages"] = messages_data
    if "max_tokens" not in payload and normalized.max_tokens is not None:
        payload["max_tokens"] = normalized.max_tokens
    if "temperature" not in payload and normalized.temperature is not None:
        payload["temperature"] = normalized.temperature
    if isinstance(payload.get("thinking"), dict) and payload["thinking"].get("type") == "enabled":
        budget = payload["thinking"].get("budget_tokens")
        if budget is None or budget > THINKING_BUDGET_TOKENS:
            payload["thinking"]["budget_tokens"] = THINKING_BUDGET_TOKENS
    return payload


def _chat_completion_message_to_anthropic_content(message: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Convert OpenAI assistant message (with tool_calls) to Anthropic content blocks."""
    content_blocks: list[Dict[str, Any]] = []

    text = message.get("content")
    if isinstance(text, str) and text.strip():
        content_blocks.append({"type": "text", "text": text})

    for tc in message.get("tool_calls", []) or []:
        function = tc.get("function", {}) or {}
        name = function.get("name", "")
        if not name:
            continue

        raw_args = function.get("arguments") or "{}"
        try:
            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            parsed_args = {}

        content_blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                "name": name,
                "input": parsed_args if isinstance(parsed_args, dict) else {},
            }
        )

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    return content_blocks


async def route_and_forward(
    normalized: Any,
    protocol: str,
    handler: Any,
    api_key: Optional[str] = None,
    source_headers: Any | None = None,
) -> Dict[str, Any]:
    """Route request and forward to provider."""
    config = get_config()
    provider, client_info = _resolve_provider(normalized, protocol, api_key)

    # Log client info if available
    if client_info:
        print(f"[brain_agent_proxy] Client: {client_info.agent_name} ({api_key})")

    # Forward request
    try:
        response = await forward_to_provider(provider, normalized, protocol, source_headers=source_headers)
    except Exception as e:
        err_text = str(e)
        # Preserve upstream Copilot 4xx semantic errors.
        # Do not hide model/endpoint compatibility errors behind proxy fallbacks.
        if err_text.startswith("Copilot API error: 4"):
            raise
        raise

    # Format response
    return handler.format_response(response)


def _resolve_provider(normalized: Any, protocol: str, api_key: Optional[str]):
    """Resolve provider and optional client info from request context.
    Prefer explicit provider/model selectors. When a request comes through a
    client key bound to exactly one provider, accept bare model names as a
    compatibility fallback for Claude Code follow-up requests.
    """
    config = get_config()
    routing_engine = RoutingEngine(config)
    provider = None
    client_info = None

    # 1. Parse model selector if explicitly provided as provider/model.
    model_selector = str(getattr(normalized, "model", "") or "")
    provider_hint, selected_model = routing_engine.parse_model_selector(model_selector)

    # 2. Resolve provider binding from client key when available.
    client_provider = ""
    if api_key:
        provider_from_key, client_info = routing_engine.find_provider_by_client_key(api_key)
        if provider_from_key:
            client_provider = provider_from_key.id
        elif client_info:
            client_provider = str(client_info.provider or "").strip()
        else:
            parsed = routing_engine.parse_client_key(api_key)
            if parsed:
                client_provider = str(parsed.get("provider") or "").strip()

    # 3. Bare model compatibility fallback for bound client keys.
    if (not provider_hint or not selected_model) and client_provider and model_selector.strip():
        provider_hint = client_provider
        selected_model = model_selector.strip()
        print(
            f"[brain_agent_proxy] DEBUG: bare model selector '{model_selector}' "
            f"resolved via client key to provider={provider_hint}"
        )

    if not provider_hint or not selected_model:
        raise ValueError(
            f"Invalid model selector '{model_selector}'. Expected format 'provider/model'. "
            "Bare model names are only supported when the client key is bound to a provider."
        )

    # 4. If both explicit provider and client provider exist, they must match.
    if client_provider and client_provider != provider_hint:
        raise ValueError(
            f"Provider mismatch: client key is bound to provider '{client_provider}', "
            f"but request specifies provider '{provider_hint}'"
        )

    # 5. Canonicalize the selected model against the resolved provider.
    provider = routing_engine._find_enabled_provider(provider_hint)
    if not provider:
        raise ValueError(f"Provider '{provider_hint}' specified in model selector '{model_selector}' not found or disabled")

    resolved_selected = provider.resolve_model(selected_model)
    if not resolved_selected:
        raise ValueError(
            f"Model '{selected_model}' is not supported by provider '{provider_hint}'. "
            f"Supported models: {provider.supported_model_ids()}"
        )

    canonical_selected = resolved_selected.id
    print(
        f"[brain_agent_proxy] DEBUG: model_selector={model_selector} -> "
        f"provider={provider.id}, model={canonical_selected} (explicit provider/model)"
    )

    normalized.model = canonical_selected
    if isinstance(getattr(normalized, "original_request", None), dict):
        normalized.original_request["model"] = canonical_selected

    return provider, client_info


async def route_and_forward_stream(
    normalized: Any,
    protocol: str,
    api_key: Optional[str] = None,
    resolved_provider: Any | None = None,
    resolved_client_info: Any | None = None,
    source_headers: Any | None = None,
):
    """Route and forward streaming request; returns async bytes iterator."""
    provider = resolved_provider
    client_info = resolved_client_info
    if provider is None:
        provider, client_info = _resolve_provider(normalized, protocol, api_key)
    if client_info:
        print(f"[brain_agent_proxy] Client: {client_info.agent_name} ({api_key})")

    # Streaming currently supported for Copilot OAuth provider path.
    if provider.type in ("oauth", "oauth_device"):
        if provider.type == "oauth":
            from .providers.github_copilot import GitHubCopilotProvider
            copilot = GitHubCopilotProvider(provider_id=provider.id)
            return copilot.forward_stream(normalized.original_request, protocol)
        from .providers.oauth_device import OAuthDeviceProvider
        cfg = provider.oauth_config or {}
        oauth_device = OAuthDeviceProvider(
            provider_id=provider.id,
            token_file=cfg.get("token_file"),
            auth_url=cfg.get("auth_url", "https://github.com/login/device/code"),
            token_url=cfg.get("token_url", "https://github.com/login/oauth/access_token"),
            scope=cfg.get("scope", ""),
            api_base_url=cfg.get("api_base_url", "http://127.0.0.1:4141"),
            require_auth=bool(cfg.get("require_auth", False)),
            header_name=cfg.get("header_name", "Authorization"),
            auth_scheme=cfg.get("auth_scheme", "Bearer"),
            client_id=cfg.get("client_id", ""),
            upstream_mode=cfg.get("upstream_mode", ""),
            codex_endpoint=cfg.get("codex_endpoint", ""),
        )
        return oauth_device.forward_stream(normalized.original_request, protocol)

    if provider.type == "gemini":
        from .providers.gemini import GeminiProvider

        api_key, api_key_env, api_base_url = _resolve_provider_secret(provider, "GEMINI_API_KEY")
        oauth_cfg = getattr(provider, "oauth_config", None) or {}
        gemini = GeminiProvider(
            provider_id=provider.id,
            api_key=api_key,
            api_key_env=api_key_env,
            api_base_url=api_base_url or "https://generativelanguage.googleapis.com/v1beta",
            oauth_token_file=oauth_cfg.get("token_file"),
            oauth_token_url=str(oauth_cfg.get("token_url", "https://oauth2.googleapis.com/token")),
            oauth_client_id=str(oauth_cfg.get("client_id", "") or ""),
            oauth_client_secret=str(oauth_cfg.get("client_secret", "") or ""),
            use_code_assist_oauth=bool(oauth_cfg.get("use_code_assist_oauth", False)),
            code_assist_endpoint=str(oauth_cfg.get("code_assist_endpoint", "https://cloudcode-pa.googleapis.com")),
            project_id=str(oauth_cfg.get("project_id", "") or ""),
        )
        return gemini.forward_stream(normalized.original_request, protocol)

    if provider.type == "claude_cli":
        from .providers.claude_cli import ClaudeCLIProvider

        cfg = getattr(provider, "claude_cli_config", None) or {}
        cli_provider = ClaudeCLIProvider(
            provider_id=provider.id,
            workdir=cfg.get("workdir"),
            permission_mode=str(cfg.get("permission_mode", "default") or "default"),
            cli_path=cfg.get("cli_path"),
        )
        return await cli_provider.forward_stream(normalized.original_request, protocol)

    if provider.id == "minimax" and _minimax_chain(provider) == "native":
        return _build_api_key_stream_iter(provider, normalized, "messages", source_headers=source_headers)

    if provider.type == "api_key":
        return _build_api_key_stream_iter(provider, normalized, protocol, source_headers=source_headers)

    raise ValueError(f"Streaming not supported for provider type {provider.type}")


def _build_api_key_stream_iter(provider: Any, normalized: Any, protocol: str, source_headers: Any | None = None):
    import httpx

    if provider.id == "minimax" and _minimax_chain(provider) == "native":
        if protocol != "messages":
            raise ValueError("MiniMax native chain supports only /v1/messages")
        minimax = _build_minimax_provider(provider)
        headers = minimax.build_headers()
        headers = _apply_passthrough_anthropic_headers(headers, source_headers)
        payload = minimax.build_messages_payload(
            getattr(normalized, "original_request", {}) or {},
            _canonicalize_upstream_model(provider, normalized.model),
        )
        payload["stream"] = True
        _rewrite_tool_names_for_provider(payload, provider)

        async def _iter():
            url = f"{minimax.get_api_base_url()}/v1/messages"
            timeout = httpx.Timeout(
                connect=STREAM_CONNECT_TIMEOUT_SECONDS,
                read=STREAM_IDLE_TIMEOUT_SECONDS,
                write=STREAM_CONNECT_TIMEOUT_SECONDS,
                pool=STREAM_CONNECT_TIMEOUT_SECONDS,
            )
            for attempt in range(STREAM_MAX_RETRIES + 1):
                try:
                    async with httpx.AsyncClient(timeout=timeout) as upstream:
                        async with upstream.stream("POST", url, json=payload, headers=headers) as resp:
                            if resp.status_code == 429:
                                body = (await resp.aread()).decode("utf-8", "ignore")
                                if attempt < STREAM_MAX_RETRIES:
                                    delay = STREAM_RETRY_BASE_DELAY * (2 ** attempt)
                                    print(f"[brain_agent_proxy] 429 from upstream, retry {attempt+1}/{STREAM_MAX_RETRIES} after {delay}s")
                                    await asyncio.sleep(delay)
                                    continue
                                raise ValueError(f"Provider returned 429 after {STREAM_MAX_RETRIES} retries: {body}")
                            if resp.status_code != 200:
                                body = (await resp.aread()).decode("utf-8", "ignore")
                                raise ValueError(f"Provider returned {resp.status_code}: {body}")
                            saw_visible_output = False
                            pending_chunks: list[bytes] = []
                            async for chunk in resp.aiter_bytes():
                                if not chunk:
                                    continue
                                if saw_visible_output:
                                    yield chunk
                                    continue
                                pending_chunks.append(chunk)
                                if _chunk_has_visible_output(chunk):
                                    saw_visible_output = True
                                    for pending in pending_chunks:
                                        yield pending
                                    pending_chunks.clear()
                            if not saw_visible_output and attempt < STREAM_MAX_RETRIES:
                                delay = STREAM_RETRY_BASE_DELAY * (2 ** attempt)
                                print(
                                    f"[brain_agent_proxy] Empty semantic SSE from upstream, retry "
                                    f"{attempt+1}/{STREAM_MAX_RETRIES} after {delay}s"
                                )
                                await asyncio.sleep(delay)
                                continue
                            for pending in pending_chunks:
                                yield pending
                            return
                except httpx.ReadTimeout:
                    if STREAM_RETRY_ON_TIMEOUT and attempt < STREAM_MAX_RETRIES:
                        delay = STREAM_RETRY_BASE_DELAY * (2 ** attempt)
                        print(f"[brain_agent_proxy] ReadTimeout, retry {attempt+1}/{STREAM_MAX_RETRIES} after {delay}s")
                        await asyncio.sleep(delay)
                        continue
                    raise

        return _iter()

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)
    headers = _apply_passthrough_anthropic_headers(headers, source_headers)

    effective_protocol = protocol
    can_messages = _provider_supports_protocol(provider, "messages")
    can_chat = _provider_supports_protocol(provider, "chat_completions")
    if protocol == "messages" and not can_messages and can_chat:
        endpoint = "/v1/chat/completions"
        effective_protocol = "chat_completions"
    elif protocol == "messages":
        endpoint = "/v1/messages"
    elif protocol == "responses":
        endpoint = "/v1/responses"
    else:
        endpoint = "/v1/chat/completions"

    if effective_protocol == "messages":
        payload = _build_anthropic_messages_payload(normalized, provider)
        payload["stream"] = True
        headers["anthropic-version"] = "2023-06-01"
    else:
        payload = dict(normalized.original_request or {})
        payload["model"] = _canonicalize_upstream_model(provider, normalized.model)
        payload["stream"] = True
    if provider.id == "kimi" and effective_protocol == "messages":
        payload, headers = _apply_kimi_upstream_shape(payload, headers, source_headers)
    _rewrite_tool_names_for_provider(payload, provider)

    async def _iter():
        url = f"{api_base_url}{endpoint}"
        timeout = httpx.Timeout(
            connect=STREAM_CONNECT_TIMEOUT_SECONDS,
            read=STREAM_IDLE_TIMEOUT_SECONDS,
            write=STREAM_CONNECT_TIMEOUT_SECONDS,
            pool=STREAM_CONNECT_TIMEOUT_SECONDS,
        )
        for attempt in range(STREAM_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as upstream:
                    async with upstream.stream("POST", url, json=payload, headers=headers) as resp:
                        if resp.status_code == 429:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            if attempt < STREAM_MAX_RETRIES:
                                delay = STREAM_RETRY_BASE_DELAY * (2 ** attempt)
                                print(f"[brain_agent_proxy] 429 from upstream, retry {attempt+1}/{STREAM_MAX_RETRIES} after {delay}s")
                                await asyncio.sleep(delay)
                                continue
                            raise ValueError(f"Provider returned 429 after {STREAM_MAX_RETRIES} retries: {body}")
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            raise ValueError(f"Provider returned {resp.status_code}: {body}")
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                yield chunk
                        return  # 成功，退出重试循环
            except httpx.ReadTimeout:
                if STREAM_RETRY_ON_TIMEOUT and attempt < STREAM_MAX_RETRIES:
                    delay = STREAM_RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"[brain_agent_proxy] ReadTimeout, retry {attempt+1}/{STREAM_MAX_RETRIES} after {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise

    return _iter()


async def route_and_forward_embeddings(model: str, body: Dict[str, Any], api_key: Optional[str] = None):
    """Route and forward embeddings requests."""
    class _EmbeddingReq:
        def __init__(self, model_name: str):
            self.model = model_name

    provider, client_info = _resolve_provider(_EmbeddingReq(model), "chat_completions", api_key)
    if client_info:
        print(f"[brain_agent_proxy] Client: {client_info.agent_name} ({api_key})")

    # OAuth Copilot path.
    if provider.type == "oauth":
        from .providers.github_copilot import GitHubCopilotProvider
        copilot = GitHubCopilotProvider(provider_id=provider.id)
        return await copilot.forward_embeddings(body)

    if provider.type == "oauth_device":
        from .providers.oauth_device import OAuthDeviceProvider
        cfg = provider.oauth_config or {}
        oauth_device = OAuthDeviceProvider(
            provider_id=provider.id,
            token_file=cfg.get("token_file"),
            auth_url=cfg.get("auth_url", "https://github.com/login/device/code"),
            token_url=cfg.get("token_url", "https://github.com/login/oauth/access_token"),
            scope=cfg.get("scope", ""),
            api_base_url=cfg.get("api_base_url", "http://127.0.0.1:4141"),
            require_auth=bool(cfg.get("require_auth", False)),
            header_name=cfg.get("header_name", "Authorization"),
            auth_scheme=cfg.get("auth_scheme", "Bearer"),
            client_id=cfg.get("client_id", ""),
            upstream_mode=cfg.get("upstream_mode", ""),
            codex_endpoint=cfg.get("codex_endpoint", ""),
        )
        return await oauth_device.forward(body, "embeddings")

    # API-key compatible upstreams.
    if provider.type == "api_key":
        import httpx

        api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
        headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{api_base_url}/v1/embeddings", json=body, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")
        return _parse_json_response(resp)

    if provider.type == "gemini":
        raise ValueError("Embeddings not supported for Gemini provider in this adapter")

    raise ValueError(f"Embeddings not supported for provider type {provider.type}")


async def forward_to_provider(
    provider: Any,
    normalized: Any,
    protocol: str,
    source_headers: Any | None = None,
) -> Dict[str, Any]:
    """Forward request to provider."""
    import httpx

    # Handle OAuth providers (new format: type == "oauth")
    if provider.type == "oauth" and provider.credentials and provider.credentials.oauth:
        from .providers.github_copilot import GitHubCopilotProvider

        copilot = GitHubCopilotProvider(provider_id=provider.id)
        return await copilot.forward(normalized.original_request, protocol)

    # Handle OAuth Device (legacy format)
    elif provider.type == "oauth_device":
        from .providers.oauth_device import OAuthDeviceProvider
        cfg = provider.oauth_config or {}
        oauth_device = OAuthDeviceProvider(
            provider_id=provider.id,
            token_file=cfg.get("token_file"),
            auth_url=cfg.get("auth_url", "https://github.com/login/device/code"),
            token_url=cfg.get("token_url", "https://github.com/login/oauth/access_token"),
            scope=cfg.get("scope", ""),
            api_base_url=cfg.get("api_base_url", "http://127.0.0.1:4141"),
            require_auth=bool(cfg.get("require_auth", False)),
            header_name=cfg.get("header_name", "Authorization"),
            auth_scheme=cfg.get("auth_scheme", "Bearer"),
            client_id=cfg.get("client_id", ""),
            upstream_mode=cfg.get("upstream_mode", ""),
            codex_endpoint=cfg.get("codex_endpoint", ""),
        )
        return await oauth_device.forward(normalized.original_request, protocol)

    elif provider.type == "claude_cli":
        from .providers.claude_cli import ClaudeCLIProvider

        cfg = getattr(provider, "claude_cli_config", None) or {}
        cli_provider = ClaudeCLIProvider(
            provider_id=provider.id,
            workdir=cfg.get("workdir"),
            permission_mode=str(cfg.get("permission_mode", "default") or "default"),
            cli_path=cfg.get("cli_path"),
        )
        return await cli_provider.forward(normalized.original_request, protocol)

    # Handle API Key providers (new format)
    elif provider.type == "api_key":
        if provider.id == "minimax" and _minimax_chain(provider) == "native":
            minimax = _build_minimax_provider(provider)
            payload = minimax.build_messages_payload(
                getattr(normalized, "original_request", {}) or {},
                _canonicalize_upstream_model(provider, normalized.model),
            )
            headers = minimax.build_headers()
            headers = _apply_passthrough_anthropic_headers(headers, source_headers)
            alias_to_original = _rewrite_tool_names_for_provider(payload, provider)

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{minimax.get_api_base_url()}/v1/messages",
                    json=payload,
                    headers=headers,
                )

            if resp.status_code != 200:
                raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")
            result = _parse_json_response(resp)
            if alias_to_original:
                _restore_tool_names_in_response(result, alias_to_original)

            raw_content = result.get("content")
            content_blocks = raw_content if isinstance(raw_content, list) else []
            content_text = ""
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    content_text += block.get("text", "")
            return {
                "id": result.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
                "model": normalized.model,
                "content": content_blocks,
                "messages": [Message(role="assistant", content=content_text)],
                "stop_reason": result.get("stop_reason", "end_turn"),
                "input_tokens": result.get("usage", {}).get("input_tokens", 0),
                "output_tokens": result.get("usage", {}).get("output_tokens", 0),
                "created": int(datetime.now().timestamp()),
            }

        api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)

        # Select endpoint based on protocol
        # For providers without native messages support, convert messages -> chat_completions
        effective_protocol = protocol
        provider_protocols = set(getattr(provider, "protocols", []) or [])
        can_messages = "messages" in provider_protocols
        can_chat = "chat_completions" in provider_protocols
        if protocol == "messages" and not can_messages and can_chat:
            endpoint = "/v1/chat/completions"
            effective_protocol = "chat_completions"
        elif protocol == "messages":
            endpoint = "/v1/messages"
        elif protocol == "responses":
            endpoint = "/v1/responses"
        elif protocol == "embeddings":
            endpoint = "/v1/embeddings"
        else:
            endpoint = "/v1/chat/completions"

    else:
        if provider.type == "gemini":
            from .providers.gemini import GeminiProvider

            api_key, api_key_env, api_base_url = _resolve_provider_secret(provider, "GEMINI_API_KEY")
            oauth_cfg = getattr(provider, "oauth_config", None) or {}
            gemini = GeminiProvider(
                provider_id=provider.id,
                api_key=api_key,
                api_key_env=api_key_env,
                api_base_url=api_base_url or "https://generativelanguage.googleapis.com/v1beta",
                oauth_token_file=oauth_cfg.get("token_file"),
                oauth_token_url=str(oauth_cfg.get("token_url", "https://oauth2.googleapis.com/token")),
                oauth_client_id=str(oauth_cfg.get("client_id", "") or ""),
                oauth_client_secret=str(oauth_cfg.get("client_secret", "") or ""),
                use_code_assist_oauth=bool(oauth_cfg.get("use_code_assist_oauth", False)),
                code_assist_endpoint=str(oauth_cfg.get("code_assist_endpoint", "https://cloudcode-pa.googleapis.com")),
                project_id=str(oauth_cfg.get("project_id", "") or ""),
            )
            return await gemini.forward(normalized.original_request, protocol)
        raise ValueError(f"Unknown provider type: {provider.type}")

    # Build request URL
    url = f"{api_base_url}{endpoint}"

    # Build payload based on protocol
    if provider.type == "api_key":
        headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)
        headers = _apply_passthrough_anthropic_headers(headers, source_headers)
    else:
        headers = {"Content-Type": "application/json"}

    if effective_protocol == "messages":
        payload = _build_anthropic_messages_payload(normalized, provider)
        headers["anthropic-version"] = "2023-06-01"
        if provider.id == "kimi":
            payload, headers = _apply_kimi_upstream_shape(payload, headers, source_headers)

    elif effective_protocol == "responses":
        # OpenAI responses format
        input_data = []
        for m in normalized.messages:
            if hasattr(m, 'role') and hasattr(m, 'content'):
                input_data.append({"type": "message", "role": m.role, "content": m.content})
            elif isinstance(m, dict):
                input_data.append({"type": "message", "role": m.get("role", "user"), "content": m.get("content", "")})

        payload = {
            "model": _canonicalize_upstream_model(provider, normalized.model),
            "input": input_data,
            "stream": normalized.stream,
        }
        if normalized.max_tokens:
            payload["max_tokens"] = normalized.max_tokens

    else:
        # OpenAI chat completions format
        messages_data = []
        for m in normalized.messages:
            if hasattr(m, 'role') and hasattr(m, 'content'):
                content = _normalize_content(m.content)
                messages_data.append({"role": m.role, "content": content})
            elif isinstance(m, dict):
                content = _normalize_content(m.get("content", ""))
                messages_data.append({"role": m.get("role", "user"), "content": content})

        payload = {
            "model": _canonicalize_upstream_model(provider, normalized.model),
            "messages": messages_data,
            "stream": normalized.stream,
        }
        if normalized.temperature is not None:
            payload["temperature"] = normalized.temperature
        tools_data = _build_openai_tools(normalized)
        if tools_data:
            payload["tools"] = tools_data
            payload["tool_choice"] = "auto"
        if normalized.max_tokens:
            payload["max_tokens"] = normalized.max_tokens

    alias_to_original: Dict[str, str] = {}
    if provider.type == "api_key":
        alias_to_original = _rewrite_tool_names_for_provider(payload, provider)

    # Forward request
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Provider returned {resp.status_code}: {resp.text}")
    result = _parse_json_response(resp)
    if provider.type == "api_key" and alias_to_original:
        _restore_tool_names_in_response(result, alias_to_original)

    # Normalize response based on effective_protocol (actual API format used)
    if effective_protocol == "messages":
        # Anthropic messages response
        raw_content = result.get("content")
        content_blocks = raw_content if isinstance(raw_content, list) else []
        content_text = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                content_text += block.get("text", "")
        return {
            "id": result.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            "model": normalized.model,
            "content": content_blocks,
            "messages": [Message(role="assistant", content=content_text)],
            "stop_reason": result.get("stop_reason", "end_turn"),
            "input_tokens": result.get("usage", {}).get("input_tokens", 0),
            "output_tokens": result.get("usage", {}).get("output_tokens", 0),
            "created": int(datetime.now().timestamp()),
        }
    elif effective_protocol == "responses":
        # OpenAI responses response
        output_text = ""
        if result.get("output"):
            for item in result["output"]:
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text += content.get("text", "")
        return {
            "id": result.get("id", f"resp_{uuid.uuid4().hex[:8]}"),
            "model": normalized.model,
            "content": output_text,
            "messages": [Message(role="assistant", content=output_text)],
            "finish_reason": "stop",
            "input_tokens": result.get("usage", {}).get("input_tokens", 0),
            "output_tokens": result.get("usage", {}).get("output_tokens", 0),
            "created": int(datetime.now().timestamp()),
        }
    elif effective_protocol == "chat_completions":
        # OpenAI chat completions response
        first_choice = result.get("choices", [{}])[0] if result.get("choices") else {}
        assistant_message = first_choice.get("message", {}) or {}
        anthropic_content = _chat_completion_message_to_anthropic_content(assistant_message)
        assistant_text = "".join(
            block.get("text", "")
            for block in anthropic_content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        stop_reason = first_choice.get("finish_reason", "stop")
        if assistant_message.get("tool_calls"):
            stop_reason = "tool_use"

        return {
            "id": result.get("id", f"chatcmpl_{uuid.uuid4().hex[:8]}"),
            "model": normalized.model,
            "content": anthropic_content,
            "messages": [Message(role="assistant", content=assistant_text)],
            "finish_reason": first_choice.get("finish_reason", "stop"),
            "stop_reason": stop_reason,
            "input_tokens": result.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": result.get("usage", {}).get("completion_tokens", 0),
            "created": int(datetime.now().timestamp()),
        }


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    """Create FastAPI app with custom config."""
    if config:
        import src.config
        src.config._config = config
    return app


@app.get("/token")
async def get_token(authorization: Optional[str] = Header(None)):
    """Return current provider token for debugging parity with copilot-api."""
    _ = authorization
    try:
        from .providers.github_copilot import GitHubCopilotProvider
        copilot = GitHubCopilotProvider()
        token = await copilot.get_current_token()
        return {"token": token}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Failed to fetch token", "token": None, "details": str(e)})


@app.get("/usage")
async def get_usage(authorization: Optional[str] = Header(None)):
    """Return Copilot usage info for parity with copilot-api."""
    _ = authorization
    try:
        from .providers.github_copilot import GitHubCopilotProvider
        copilot = GitHubCopilotProvider()
        usage = await copilot.get_usage()
        return usage
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Failed to fetch Copilot usage", "details": str(e)})


@app.get("/check-usage")
async def check_usage(authorization: Optional[str] = Header(None)):
    """HTTP equivalent of copilot-api `check-usage` command."""
    return await get_usage(authorization)


@app.get("/v1/usage")
async def get_usage_v1(authorization: Optional[str] = Header(None)):
    """OpenAI-style namespace alias."""
    return await get_usage(authorization)


@app.get("/approvals")
async def list_approvals():
    """List pending/recent manual approval records."""
    out = []
    async with _approval_lock:
        for rec in _pending_approvals.values():
            out.append(
                {
                    "id": rec.get("id"),
                    "path": rec.get("path"),
                    "model": rec.get("model"),
                    "created_at": rec.get("created_at"),
                    "status": rec.get("status"),
                    "decision": rec.get("decision"),
                }
            )
    out.sort(key=lambda x: int(x.get("created_at", 0)), reverse=True)
    return {"manual_approval": MANUAL_APPROVAL, "items": out}


@app.post("/approvals/{approval_id}/approve")
async def approve_request(approval_id: str):
    async with _approval_lock:
        rec = _pending_approvals.get(approval_id)
        if not rec:
            return JSONResponse(status_code=404, content={"error": "approval not found"})
        rec["status"] = "approved"
        rec["decision"] = "approved"
        event = rec.get("event")
        if isinstance(event, asyncio.Event):
            event.set()
    return {"ok": True, "id": approval_id, "decision": "approved"}


@app.post("/approvals/{approval_id}/deny")
async def deny_request(approval_id: str):
    async with _approval_lock:
        rec = _pending_approvals.get(approval_id)
        if not rec:
            return JSONResponse(status_code=404, content={"error": "approval not found"})
        rec["status"] = "denied"
        rec["decision"] = "denied"
        event = rec.get("event")
        if isinstance(event, asyncio.Event):
            event.set()
    return {"ok": True, "id": approval_id, "decision": "denied"}


@app.get("/debug")
async def get_debug():
    """Debug info endpoint for runtime parity and diagnostics."""
    import platform
    from pathlib import Path

    token_path = Path("~/.local/share/brain_agent_proxy/tokens/copilot.json").expanduser()
    github_token_path = Path("~/.local/share/brain_agent_proxy/tokens/github_oauth.json").expanduser()
    cfg = get_config()
    return {
        "service": "brain_agent_proxy",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "providers_enabled": [p.id for p in cfg.providers if p.enabled],
        "host": cfg.host,
        "port": cfg.port,
        "token_exists": token_path.exists(),
        "token_path": str(token_path),
        "github_token_exists": github_token_path.exists(),
        "github_token_path": str(github_token_path),
        "manual_approval": MANUAL_APPROVAL,
        "manual_approval_timeout_seconds": MANUAL_APPROVAL_TIMEOUT_SECONDS,
        "rate_limit_seconds": RATE_LIMIT_SECONDS,
        "rate_limit_wait": RATE_LIMIT_WAIT,
        "pending_approval_count": len(_pending_approvals),
        "version": "1.0.0",
    }


@app.get("/debug/recent_requests")
async def get_recent_requests(limit: int = 20):
    limit = max(1, min(limit, RECENT_REQUESTS_LIMIT))
    async with _recent_requests_lock:
        items = [_public_request_record(item) for item in list(_recent_requests)[-limit:]]

    completed = sum(1 for item in items if item.get("state") in {"completed", "stream_completed"})
    errors = sum(1 for item in items if "error" in str(item.get("state", "")))
    active = sum(1 for item in items if item.get("state") == "started")

    return {
        "limit": limit,
        "buffer_size": RECENT_REQUESTS_LIMIT,
        "tracked_paths": sorted(TRACEABLE_PATHS),
        "summary": {
            "returned": len(items),
            "completed": completed,
            "errors": errors,
            "active": active,
        },
        "items": list(reversed(items)),
    }


@app.post("/reload-config")
async def reload_config_endpoint():
    """Reload providers.yaml, proxy.yaml, context_windows.json without restarting."""
    try:
        cfg = reload_config()
        return {
            "ok": True,
            "providers": [p.id for p in cfg.providers],
            "proxy_clients": len(cfg.proxy.clients) if cfg.proxy else 0,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/reload-secrets")
async def reload_secrets():
    """Reload secrets from the configured env files into os.environ without restarting."""
    updated = []
    errors = []
    for env_path in SECRETS_ENV_PATHS:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key:
                        os.environ[key] = val
                        updated.append(key)
        except FileNotFoundError:
            errors.append(f"secrets file not found: {env_path}")
        except Exception as e:
            errors.append(f"{env_path}: {e}")

    if not updated:
        return {"ok": False, "error": "; ".join(errors) or "no secrets loaded"}

    return {"ok": True, "updated": len(updated), "keys": updated, "errors": errors}


if __name__ == "__main__":
    import uvicorn

    config = get_config()
    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,
    )
