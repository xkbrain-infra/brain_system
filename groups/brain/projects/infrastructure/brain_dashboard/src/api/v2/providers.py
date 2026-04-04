"""Provider OAuth Configuration API.

Manages reading/writing brain_agent_proxy providers.yaml and
orchestrating OAuth flows for all provider types.
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/providers", tags=["providers"])

PROVIDERS_YAML = Path("/brain/infrastructure/service/brain_agent_proxy/config/providers.yaml")

# In-memory registry of active OAuth flows: provider_id → flow_state
_active_flows: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask(value: str | None, show: int = 8) -> str | None:
    """Return first `show` chars + *** for non-empty secrets."""
    if not value:
        return None
    if value.startswith("${"):
        return value  # env var reference — show as-is
    return value[:show] + "***" if len(value) > show else "***"


def _load_providers() -> dict:
    if not PROVIDERS_YAML.exists():
        return {}
    with open(PROVIDERS_YAML) as f:
        data = yaml.safe_load(f) or {}
    return data.get("providers", {})


def _load_full_yaml() -> dict:
    if not PROVIDERS_YAML.exists():
        return {"providers": {}}
    with open(PROVIDERS_YAML) as f:
        return yaml.safe_load(f) or {"providers": {}}


def _save_full_yaml(data: dict) -> None:
    with open(PROVIDERS_YAML, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _token_file_path(raw: str) -> Path:
    return Path(os.path.expanduser(raw))


def _read_token_file(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _write_token_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _sanitize_provider(pid: str, cfg: dict) -> dict:
    """Return provider config with secrets masked."""
    ptype = cfg.get("type", "unknown")
    result: dict[str, Any] = {
        "id": pid,
        "name": cfg.get("name", pid),
        "type": ptype,
        "description": cfg.get("description", ""),
        "enabled": cfg.get("enabled", True),
        "priority": cfg.get("priority", 99),
        "models": cfg.get("models", []),
        "capabilities": cfg.get("capabilities", []),
        "protocols": cfg.get("protocols", []),
    }

    # Auth status per type
    if ptype == "oauth":
        oauth = cfg.get("oauth", {})
        token = oauth.get("access_token", "")
        result["auth_status"] = {
            "has_token": bool(token and not token.startswith("gho_xxx")),
            "expires_at": oauth.get("expires_at"),
            "client_id": oauth.get("client_id"),
            "client_secret_configured": bool(oauth.get("client_secret")),
            "access_token_preview": _mask(token),
        }

    elif ptype == "oauth_device":
        oauth_cfg = cfg.get("oauth_config", {})
        tf = oauth_cfg.get("token_file", "")
        token_data = _read_token_file(_token_file_path(tf)) if tf else {}
        result["auth_status"] = {
            "has_token": bool(token_data.get("access_token") or token_data.get("token")),
            "client_id": oauth_cfg.get("client_id"),
            "token_file": tf,
            "token_preview": _mask(token_data.get("access_token") or token_data.get("token")),
        }

    elif ptype == "gemini":
        oauth_cfg = cfg.get("oauth_config", {})
        tf = oauth_cfg.get("token_file", "")
        token_data = _read_token_file(_token_file_path(tf)) if tf else {}
        result["auth_status"] = {
            "has_token": bool(token_data.get("access_token")),
            "client_id_env": oauth_cfg.get("client_id_env"),
            "client_id_configured": bool(os.environ.get(oauth_cfg.get("client_id_env", ""), "")),
            "token_file": tf,
            "token_preview": _mask(token_data.get("access_token")),
        }

    elif ptype == "api_key":
        api_cfg = cfg.get("api_key", {})
        env_var = api_cfg.get("api_key_env", "")
        literal = api_cfg.get("key_value", "")
        has_key = bool(literal) or bool(os.environ.get(env_var, ""))
        result["auth_status"] = {
            "has_key": has_key,
            "api_key_env": env_var,
            "key_value_preview": _mask(literal or os.environ.get(env_var, "")),
            "api_base_url": api_cfg.get("api_base_url", ""),
        }

    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_providers() -> list[dict]:
    """List all providers with sanitized config, sorted by priority."""
    providers = _load_providers()
    result = [_sanitize_provider(pid, cfg) for pid, cfg in providers.items()]
    result.sort(key=lambda p: p.get("priority", 99))
    return result


@router.get("/{provider_id}")
async def get_provider(provider_id: str) -> dict:
    """Get single provider config (sanitized)."""
    providers = _load_providers()
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return _sanitize_provider(provider_id, providers[provider_id])


class ApiKeyConfig(BaseModel):
    key_value: str
    api_base_url: str = ""


@router.post("/{provider_id}/config")
async def save_api_key_config(provider_id: str, body: ApiKeyConfig) -> dict:
    """Save api_key provider configuration."""
    data = _load_full_yaml()
    providers = data.get("providers", {})
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    cfg = providers[provider_id]
    if cfg.get("type") != "api_key":
        raise HTTPException(status_code=400, detail="Only api_key type providers support this endpoint")

    if "api_key" not in cfg:
        cfg["api_key"] = {}
    cfg["api_key"]["key_value"] = body.key_value
    if body.api_base_url:
        cfg["api_key"]["api_base_url"] = body.api_base_url

    _save_full_yaml(data)
    return {"status": "saved", "provider_id": provider_id}


@router.post("/{provider_id}/toggle")
async def toggle_provider(provider_id: str) -> dict:
    """Toggle provider enabled/disabled."""
    data = _load_full_yaml()
    providers = data.get("providers", {})
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    current = providers[provider_id].get("enabled", True)
    providers[provider_id]["enabled"] = not current
    _save_full_yaml(data)
    return {"provider_id": provider_id, "enabled": not current}


@router.post("/{provider_id}/oauth/start")
async def start_oauth_flow(provider_id: str) -> dict:
    """Initiate OAuth flow for a provider.

    Returns flow info:
    - oauth type: {flow: 'code', auth_url}
    - oauth_device type: {flow: 'device', user_code, verification_uri, expires_in}
    - gemini type: {flow: 'pkce', auth_url}
    """
    providers = _load_providers()
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    cfg = providers[provider_id]
    ptype = cfg.get("type")

    if ptype == "oauth":
        return await _start_authorization_code_flow(provider_id, cfg)
    elif ptype == "oauth_device":
        return await _start_device_code_flow(provider_id, cfg)
    elif ptype == "gemini":
        return await _start_pkce_flow(provider_id, cfg)
    else:
        raise HTTPException(status_code=400, detail=f"Provider type '{ptype}' does not support OAuth flow initiation")


@router.get("/{provider_id}/oauth/poll")
async def poll_oauth_flow(provider_id: str) -> dict:
    """Poll device code flow status.

    Returns:
    - {status: 'pending'} — still waiting for user
    - {status: 'success'} — token obtained and saved
    - {status: 'expired'} — flow expired, re-initiate
    - {status: 'error', detail: str}
    """
    flow = _active_flows.get(provider_id)
    if not flow:
        return {"status": "no_active_flow"}

    if flow.get("type") != "device":
        return {"status": "not_a_device_flow"}

    if time.time() > flow.get("expires_at", 0):
        _active_flows.pop(provider_id, None)
        return {"status": "expired"}

    return await _poll_device_token(provider_id, flow)


# ---------------------------------------------------------------------------
# OAuth flow implementations
# ---------------------------------------------------------------------------

async def _start_authorization_code_flow(provider_id: str, cfg: dict) -> dict:
    """GitHub-style authorization code flow (copilot)."""
    oauth = cfg.get("oauth", {})
    client_id = oauth.get("client_id", "")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id not configured")

    state = secrets.token_urlsafe(32)
    redirect_uri = "http://localhost:8080/oauth2callback"

    # GitHub OAuth authorize URL
    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&scope=read:user"
    )

    _active_flows[provider_id] = {
        "type": "code",
        "state": state,
        "provider_id": provider_id,
        "redirect_uri": redirect_uri,
        "token_endpoint": oauth.get("auth_endpoint", "https://github.com/login/oauth/access_token"),
        "client_id": client_id,
        "client_secret": oauth.get("client_secret", ""),
        "started_at": time.time(),
    }

    return {"flow": "code", "auth_url": auth_url, "state": state}


async def _start_device_code_flow(provider_id: str, cfg: dict) -> dict:
    """OAuth 2.0 Device Authorization Grant (openai)."""
    oauth_cfg = cfg.get("oauth_config", {})
    auth_url = oauth_cfg.get("auth_url", "")
    client_id = oauth_cfg.get("client_id", "")

    if not auth_url or not client_id:
        raise HTTPException(status_code=400, detail="oauth_config incomplete: auth_url or client_id missing")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                auth_url,
                json={"client_id": client_id},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Device auth request failed: {e}")

    device_code = data.get("device_code", "")
    user_code = data.get("user_code", "")
    verification_uri = data.get("verification_uri") or data.get("verification_url", "")
    expires_in = data.get("expires_in", 300)
    interval = data.get("interval", 5)

    _active_flows[provider_id] = {
        "type": "device",
        "device_code": device_code,
        "provider_id": provider_id,
        "poll_url": oauth_cfg.get("poll_url", ""),
        "token_url": oauth_cfg.get("token_url", ""),
        "client_id": client_id,
        "token_file": oauth_cfg.get("token_file", ""),
        "interval": interval,
        "expires_at": time.time() + expires_in,
        "last_poll": 0.0,
    }

    return {
        "flow": "device",
        "user_code": user_code,
        "verification_uri": verification_uri,
        "expires_in": expires_in,
        "interval": interval,
    }


async def _start_pkce_flow(provider_id: str, cfg: dict) -> dict:
    """PKCE Authorization Code flow (gemini/google)."""
    oauth_cfg = cfg.get("oauth_config", {})
    client_id = os.environ.get(oauth_cfg.get("client_id_env", ""), oauth_cfg.get("client_id", ""))
    client_secret = os.environ.get(oauth_cfg.get("client_secret_env", ""), oauth_cfg.get("client_secret", ""))

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail=f"client_id not configured. Set env var: {oauth_cfg.get('client_id_env', 'GEMINI_OAUTH_CLIENT_ID')}"
        )

    # Generate PKCE code_verifier and code_challenge
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    state = secrets.token_urlsafe(32)
    redirect_uri = "http://localhost:8080/oauth2callback"
    scope = oauth_cfg.get("scope", "https://www.googleapis.com/auth/cloud-platform")

    auth_url = (
        f"{oauth_cfg.get('auth_url', 'https://accounts.google.com/o/oauth2/v2/auth')}"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&access_type=offline"
    )

    _active_flows[provider_id] = {
        "type": "pkce",
        "state": state,
        "provider_id": provider_id,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "token_url": oauth_cfg.get("token_url", "https://oauth2.googleapis.com/token"),
        "client_id": client_id,
        "client_secret": client_secret,
        "token_file": oauth_cfg.get("token_file", ""),
        "started_at": time.time(),
    }

    return {"flow": "pkce", "auth_url": auth_url, "state": state}


async def _poll_device_token(provider_id: str, flow: dict) -> dict:
    """Poll token endpoint for device code flow completion."""
    now = time.time()
    min_interval = flow.get("interval", 5)
    if now - flow.get("last_poll", 0) < min_interval:
        return {"status": "pending", "reason": "too_soon"}

    flow["last_poll"] = now

    poll_url = flow.get("poll_url") or flow.get("token_url", "")
    if not poll_url:
        return {"status": "error", "detail": "poll_url not configured"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                poll_url,
                json={
                    "client_id": flow["client_id"],
                    "device_code": flow["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
        except httpx.HTTPError as e:
            return {"status": "error", "detail": str(e)}

    error = data.get("error", "")
    if error == "authorization_pending":
        return {"status": "pending"}
    elif error == "slow_down":
        flow["interval"] = min_interval + 5
        return {"status": "pending", "reason": "slow_down"}
    elif error == "expired_token":
        _active_flows.pop(provider_id, None)
        return {"status": "expired"}
    elif error:
        return {"status": "error", "detail": error}

    # Success — save token
    access_token = data.get("access_token", "")
    if not access_token:
        return {"status": "pending"}

    tf_path = _token_file_path(flow.get("token_file", ""))
    if tf_path.name:
        _write_token_file(tf_path, {
            "access_token": access_token,
            "refresh_token": data.get("refresh_token", ""),
            "token_type": data.get("token_type", "Bearer"),
            "expires_in": data.get("expires_in"),
            "obtained_at": int(time.time()),
        })

    _active_flows.pop(provider_id, None)
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Callback handler (called from app.py)
# ---------------------------------------------------------------------------

async def handle_oauth_callback(provider_id: str | None, code: str, state: str) -> dict:
    """Exchange authorization code for token. Called from /oauth2callback route.

    Returns:
        {"status": "success", "provider_id": ...} or raises HTTPException
    """
    # Find flow by state token
    matched_pid = provider_id
    if not matched_pid:
        for pid, flow in _active_flows.items():
            if flow.get("state") == state:
                matched_pid = pid
                break

    if not matched_pid or matched_pid not in _active_flows:
        raise HTTPException(status_code=400, detail="Unknown or expired OAuth state")

    flow = _active_flows[matched_pid]
    ftype = flow.get("type")

    if ftype == "code":
        result = await _exchange_authorization_code(matched_pid, flow, code)
    elif ftype == "pkce":
        result = await _exchange_pkce_code(matched_pid, flow, code)
    else:
        raise HTTPException(status_code=400, detail=f"Unexpected flow type '{ftype}' for callback")

    _active_flows.pop(matched_pid, None)
    return result


async def _exchange_authorization_code(provider_id: str, flow: dict, code: str) -> dict:
    """Exchange GitHub authorization code for access token (copilot)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            flow["token_endpoint"],
            json={
                "client_id": flow["client_id"],
                "client_secret": flow["client_secret"],
                "code": code,
                "redirect_uri": flow["redirect_uri"],
            },
            headers={"Accept": "application/json"},
        )

    try:
        data = resp.json()
    except Exception:
        # GitHub sometimes returns URL-encoded form
        import urllib.parse
        data = dict(urllib.parse.parse_qsl(resp.text))

    access_token = data.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {data}")

    # Write to providers.yaml
    full = _load_full_yaml()
    providers = full.get("providers", {})
    if provider_id in providers:
        oauth = providers[provider_id].setdefault("oauth", {})
        oauth["access_token"] = access_token
        oauth["refresh_token"] = data.get("refresh_token", oauth.get("refresh_token", ""))
        oauth["token_type"] = data.get("token_type", "bearer")
        oauth["expires_at"] = int(time.time()) + data.get("expires_in", 28800)
        _save_full_yaml(full)

    return {"status": "success", "provider_id": provider_id}


async def _exchange_pkce_code(provider_id: str, flow: dict, code: str) -> dict:
    """Exchange PKCE authorization code for token (gemini/google)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            flow["token_url"],
            data={
                "client_id": flow["client_id"],
                "client_secret": flow["client_secret"],
                "code": code,
                "code_verifier": flow["code_verifier"],
                "redirect_uri": flow["redirect_uri"],
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {resp.text}")

    data = resp.json()
    access_token = data.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=400, detail=f"No access_token in response: {data}")

    tf_path = _token_file_path(flow.get("token_file", ""))
    if tf_path.name:
        _write_token_file(tf_path, {
            "access_token": access_token,
            "refresh_token": data.get("refresh_token", ""),
            "token_type": data.get("token_type", "Bearer"),
            "expires_in": data.get("expires_in"),
            "id_token": data.get("id_token", ""),
            "obtained_at": int(time.time()),
        })

    return {"status": "success", "provider_id": provider_id}
