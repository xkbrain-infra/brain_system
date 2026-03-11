"""FastAPI application for brain_agent_proxy."""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Header

from .config import AppConfig, get_config
from .observability.health import HealthChecker
from .protocol import messages, chat_completions, responses
from .protocol.base import Message
from .routing.engine import RoutingEngine

# Allow any API key for local testing (skip validation)
# When "*" is in the list, any key is allowed
ALLOWED_API_KEYS = ["*"]
MODEL_ID_MODE = os.environ.get("BRAIN_AGENT_PROXY_MODEL_ID_MODE", "bare").strip().lower() or "bare"


class ProxyPolicyError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


RATE_LIMIT_SECONDS = float(os.environ.get("BRAIN_AGENT_PROXY_RATE_LIMIT_SECONDS", "0") or 0)
RATE_LIMIT_WAIT = os.environ.get("BRAIN_AGENT_PROXY_RATE_LIMIT_WAIT", "1").strip().lower() not in ("0", "false", "no")
MANUAL_APPROVAL = os.environ.get("BRAIN_AGENT_PROXY_MANUAL_APPROVAL", "0").strip().lower() in ("1", "true", "yes")
MANUAL_APPROVAL_TIMEOUT_SECONDS = int(
    os.environ.get("BRAIN_AGENT_PROXY_MANUAL_APPROVAL_TIMEOUT_SECONDS", "300") or 300
)

_rate_limit_lock = asyncio.Lock()
_last_request_ts = 0.0

_approval_lock = asyncio.Lock()
_pending_approvals: Dict[str, Dict[str, Any]] = {}


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
        models.append({
            "id": exposed_id,
            "object": "model",
            "provider": provider_id,
            "provider_type": provider_type,
            "cli_type": cli_type,
            "capabilities": capabilities,
            "name": name,
            "vendor": vendor,
        })


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


def _model_token_key(model_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(model_name or "").strip().lower()).strip("_")


def _resolve_model_from_token(provider: Any, token_model: str, request_model: str) -> str:
    token_model = str(token_model or "").strip()
    request_model = str(request_model or "").strip()
    if not token_model:
        return request_model
    if token_model == request_model:
        return request_model
    if _model_token_key(request_model) == token_model:
        return request_model
    for candidate in getattr(provider, "models", []) or []:
        candidate_str = str(candidate or "").strip()
        if candidate_str and _model_token_key(candidate_str) == token_model:
            return candidate_str
    return token_model


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


def _sse(event: str, payload: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def _anthropic_message_to_sse(message: Dict[str, Any]):
    """Convert one Anthropic message response to SSE event stream."""
    usage = message.get("usage", {}) or {}
    model = message.get("model", "")
    msg_id = message.get("id", f"msg_{uuid.uuid4().hex[:8]}")
    content = message.get("content", []) or []

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": 0,
            },
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


async def _openai_sse_to_anthropic_sse(raw_iter):
    """Translate OpenAI chat-completions SSE stream into Anthropic messages SSE."""
    buffer = ""
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    model = ""
    started = False
    stopped = False
    next_block_index = 0
    text_block_index = None
    tool_blocks: Dict[int, Dict[str, Any]] = {}

    async def _emit_message_start(input_tokens: int = 0):
        nonlocal started
        if started:
            return
        started = True
        return _sse("message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
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

    async for chunk in raw_iter:
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
                if stopped:
                    continue
                if text_block_index is not None:
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                    text_block_index = None
                for info in list(tool_blocks.values()):
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})
                tool_blocks.clear()
                yield _sse("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                })
                yield _sse("message_stop", {"type": "message_stop"})
                stopped = True

                continue

            try:
                obj = json.loads(data)
            except Exception:
                continue

            if obj.get("id"):
                message_id = obj.get("id")
            if obj.get("model"):
                model = obj.get("model")

            # OpenAI Responses/Codex stream event translation.
            event_type = str(obj.get("type", "") or "")
            if event_type:
                if event_type == "response.created":
                    response_obj = obj.get("response", {}) or {}
                    if response_obj.get("id"):
                        message_id = response_obj.get("id")
                    if response_obj.get("model"):
                        model = response_obj.get("model")
                    if not started:
                        evt = await _emit_message_start(0)
                        if evt:
                            yield evt
                    continue
                if event_type == "response.output_text.delta":
                    if not started:
                        evt = await _emit_message_start(0)
                        if evt:
                            yield evt
                    text = obj.get("delta")
                    if isinstance(text, str) and text:
                        if text_block_index is None:
                            text_block_index = next_block_index
                            next_block_index += 1
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": text_block_index,
                                "content_block": {"type": "text", "text": ""},
                            })
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": text_block_index,
                            "delta": {"type": "text_delta", "text": text},
                        })
                    continue
                if event_type == "response.completed":
                    response_obj = obj.get("response", {}) or {}
                    usage_obj = response_obj.get("usage", {}) or {}
                    if not started:
                        evt = await _emit_message_start(usage_obj.get("input_tokens", 0))
                        if evt:
                            yield evt
                    if text_block_index is not None:
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                        text_block_index = None
                    if not stopped:
                        yield _sse("message_delta", {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                            "usage": {"output_tokens": usage_obj.get("output_tokens", 0)},
                        })
                        yield _sse("message_stop", {"type": "message_stop"})
                        stopped = True
                    continue

            usage = obj.get("usage", {}) or {}
            prompt_tokens = usage.get("prompt_tokens", 0)
            cached_tokens = (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
            if not started:
                evt = await _emit_message_start(max(0, prompt_tokens - cached_tokens))
                if evt:
                    yield evt

            choices = obj.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta", {}) or {}

            # Text delta
            text = delta.get("content")
            if isinstance(text, str) and text:
                if text_block_index is None:
                    text_block_index = next_block_index
                    next_block_index += 1
                    yield _sse("content_block_start", {
                        "type": "content_block_start",
                        "index": text_block_index,
                        "content_block": {"type": "text", "text": ""},
                    })
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": text_block_index,
                    "delta": {"type": "text_delta", "text": text},
                })

            # Tool call delta
            for tc in (delta.get("tool_calls") or []):
                tc_index = tc.get("index")
                if tc_index is None:
                    continue
                info = tool_blocks.get(tc_index)

                tc_id = tc.get("id")
                fn = tc.get("function", {}) or {}
                fn_name = fn.get("name")
                args_delta = fn.get("arguments", "")

                if info is None and tc_id and fn_name:
                    if text_block_index is not None:
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                        text_block_index = None
                    info = {
                        "anthropic_index": next_block_index,
                        "id": tc_id,
                        "name": fn_name,
                    }
                    next_block_index += 1
                    tool_blocks[tc_index] = info
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
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": info["anthropic_index"],
                        "delta": {"type": "input_json_delta", "partial_json": args_delta},
                    })

            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not stopped:
                if text_block_index is not None:
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
                    text_block_index = None
                for info in list(tool_blocks.values()):
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})
                tool_blocks.clear()

                completion_tokens = usage.get("completion_tokens", 0)
                yield _sse("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": _map_stop_reason(finish_reason), "stop_sequence": None},
                    "usage": {"output_tokens": completion_tokens},
                })
                yield _sse("message_stop", {"type": "message_stop"})
                stopped = True

    # Upstream stream may close without [DONE]/finish event.
    if not stopped:
        if not started:
            evt = await _emit_message_start(0)
            if evt:
                yield evt
        if text_block_index is not None:
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_block_index})
            text_block_index = None
        for info in list(tool_blocks.values()):
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": info["anthropic_index"]})
        tool_blocks.clear()
        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        })
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
        before = len(models)
        _append_model_entries(models, **kwargs)
        if len(models) == before:
            return
        unique_models = []
        for entry in models:
            model_id = str(entry.get("id", "") or "")
            if not model_id or model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            unique_models.append(entry)
        models[:] = unique_models

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
                model_id=model,
                provider_id=provider.id,
                provider_type=provider.type,
                cli_type=getattr(provider, "cli_type", "chat_completions"),
                capabilities=getattr(provider, "capabilities", []) or [],
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
                result = await route_and_forward(non_stream_normalized, "messages", handler, api_key)
                return StreamingResponse(_anthropic_message_to_sse(result), media_type="text/event-stream")
            stream_iter = await route_and_forward_stream(normalized, "messages", api_key)
            if (
                (provider.type == "api_key" and _provider_supports_protocol(provider, "messages"))
                or (provider.id == "copilot" and _copilot_prefers_native_messages(normalized.model))
            ):
                return StreamingResponse(stream_iter, media_type="text/event-stream")
            return StreamingResponse(_openai_sse_to_anthropic_sse(stream_iter), media_type="text/event-stream")
        result = await route_and_forward(normalized, "messages", handler, api_key)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=500,
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

    token_count = input_tokens + output_tokens
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
            stream_iter = await route_and_forward_stream(normalized, "chat_completions", api_key)
            return StreamingResponse(stream_iter, media_type="text/event-stream")
        result = await route_and_forward(normalized, "chat_completions", handler, api_key)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=500,
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
        result = await route_and_forward(normalized, "responses", handler, api_key)
        return result
    except ProxyPolicyError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
    except Exception as e:
        return JSONResponse(
            status_code=500,
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
            status_code=500,
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


def _build_anthropic_messages_payload(normalized: Any) -> Dict[str, Any]:
    """Build Anthropic messages payload while preserving original block structure."""
    payload = dict(getattr(normalized, "original_request", {}) or {})
    payload["model"] = normalized.model
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
) -> Dict[str, Any]:
    """Route request and forward to provider."""
    config = get_config()
    provider, client_info = _resolve_provider(normalized, protocol, api_key)

    # Log client info if available
    if client_info:
        print(f"[brain_agent_proxy] Client: {client_info.agent_name} ({api_key})")

    # Forward request
    try:
        response = await forward_to_provider(provider, normalized, protocol)
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
    严格前后端分离: 前端配置什么就用什么, 服务端只做校验, 不做自动兜底
    """
    config = get_config()
    routing_engine = RoutingEngine(config)
    provider = None
    client_info = None

    # 1. 优先从请求的model字段解析provider (前端指定的优先级最高)
    model_selector = str(getattr(normalized, "model", "") or "")
    provider_hint, _, selected_model = model_selector.partition("/")

    if provider_hint and selected_model:
        # 前端明确指定了provider, 必须严格匹配, 不做兜底
        provider = routing_engine._find_enabled_provider(provider_hint)
        if not provider:
            raise ValueError(f"Provider '{provider_hint}' specified in model selector '{model_selector}' not found or disabled")

        # 校验provider是否支持该模型
        if selected_model not in provider.models:
            raise ValueError(f"Model '{selected_model}' is not supported by provider '{provider_hint}'. Supported models: {provider.models}")

        print(f"[brain_agent_proxy] DEBUG: model_selector={model_selector} -> provider={provider.id}, model={selected_model} (strict match from model prefix)")

        # 更新normalized.model为去掉前缀的模型名
        normalized.model = selected_model
        if isinstance(getattr(normalized, "original_request", None), dict):
            normalized.original_request["model"] = selected_model

        return provider, client_info

    # 2. 如果model里没有provider前缀, 必须从token解析, 不做兜底
    if api_key:
        parsed = routing_engine.parse_client_key(api_key)
        if not parsed:
            raise ValueError(f"Invalid API key format. Expected canonical format: bgw-apx-v1--p-{{provider}}--m-{{model}}--n-{{name}}")

        # 校验provider存在
        provider = routing_engine._find_enabled_provider(parsed["provider"])
        if not provider:
            raise ValueError(f"Provider '{parsed['provider']}' from API key not found or disabled")

        parsed_model = _resolve_model_from_token(provider, parsed.get("model", ""), normalized.model)

        # 校验token里的模型和请求的模型一致
        if parsed_model and parsed_model != normalized.model:
            raise ValueError(f"Model mismatch: API key specifies model '{parsed['model']}', but request specifies model '{normalized.model}'")

        # 校验provider是否支持该模型
        if normalized.model not in provider.models:
            raise ValueError(f"Model '{normalized.model}' is not supported by provider '{provider.id}'. Supported models: {provider.models}")

        if parsed_model:
            print(f"[brain_agent_proxy] DEBUG: client_key={api_key} -> provider={provider.id}, model={normalized.model} (strict match from token)")
        else:
            print(f"[brain_agent_proxy] DEBUG: client_key={api_key} -> provider={provider.id}, model={normalized.model} (legacy token without model)")
        return provider, client_info

    # 3. 两者都没有的话直接报错, 不做任何自动路由兜底
    raise ValueError(
        "No provider specified. You must either:\n"
        "1. Specify provider in model selector format: 'provider/model_name'\n"
        "2. Use a valid canonical API key that includes provider information"
    )


async def route_and_forward_stream(
    normalized: Any,
    protocol: str,
    api_key: Optional[str] = None,
):
    """Route and forward streaming request; returns async bytes iterator."""
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

    if provider.type == "api_key":
        return _build_api_key_stream_iter(provider, normalized, protocol)

    raise ValueError(f"Streaming not supported for provider type {provider.type}")


def _build_api_key_stream_iter(provider: Any, normalized: Any, protocol: str):
    import httpx

    api_base_url, require_auth, key_env, header_name, auth_scheme = _resolve_api_key_settings(provider)
    headers = _build_api_key_headers(provider, require_auth, key_env, header_name, auth_scheme)

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
        payload = _build_anthropic_messages_payload(normalized)
        payload["stream"] = True
        headers["anthropic-version"] = "2023-06-01"
    else:
        payload = dict(normalized.original_request or {})
        payload["model"] = normalized.model
        payload["stream"] = True
    _rewrite_tool_names_for_provider(payload, provider)

    async def _iter():
        url = f"{api_base_url}{endpoint}"
        async with httpx.AsyncClient(timeout=None) as upstream:
            async with upstream.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"Provider returned {resp.status_code}: {body}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk

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


async def forward_to_provider(provider: Any, normalized: Any, protocol: str) -> Dict[str, Any]:
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

    # Handle API Key providers (new format)
    elif provider.type == "api_key":
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
    else:
        headers = {"Content-Type": "application/json"}

    if effective_protocol == "messages":
        payload = _build_anthropic_messages_payload(normalized)
        headers["anthropic-version"] = "2023-06-01"

    elif effective_protocol == "responses":
        # OpenAI responses format
        input_data = []
        for m in normalized.messages:
            if hasattr(m, 'role') and hasattr(m, 'content'):
                input_data.append({"type": "message", "role": m.role, "content": m.content})
            elif isinstance(m, dict):
                input_data.append({"type": "message", "role": m.get("role", "user"), "content": m.get("content", "")})

        payload = {
            "model": normalized.model,
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
            "model": normalized.model,
            "messages": messages_data,
            "temperature": normalized.temperature,
            "stream": normalized.stream,
        }
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
        content = ""
        if result.get("content"):
            for block in result["content"]:
                if block.get("type") == "text":
                    content += block.get("text", "")
        return {
            "id": result.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            "model": normalized.model,
            "content": content,
            "messages": [Message(role="assistant", content=content)],
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
