"""Tests for Provider OAuth Configuration API.

Feature ID: brain-dashboard-oauth-config-2026-03-17
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, '/workspace/project/src')

from app import app

client = TestClient(app)


# ============================================================
# Fixtures
# ============================================================

SAMPLE_PROVIDERS = {
    "providers": {
        "copilot": {
            "type": "oauth",
            "name": "GitHub Copilot (OAuth)",
            "description": "Copilot with OAuth authentication",
            "enabled": True,
            "priority": 20,
            "models": ["gpt-4o"],
            "protocols": ["messages"],
            "capabilities": ["code"],
            "oauth": {
                "auth_endpoint": "https://github.com/login/oauth/access_token",
                "client_id": "Iv1.testclientid",
                "client_secret": "${GITHUB_CLIENT_SECRET}",
                "access_token": "gho_realtoken1234",
                "refresh_token": "gho_refresh5678",
                "token_type": "bearer",
                "expires_at": 9999999999,
                "scope": "read:user",
            },
            "api_base_url": "https://api.github.com",
        },
        "openai": {
            "type": "oauth_device",
            "name": "OpenAI (OAuth Device)",
            "description": "OpenAI via device code",
            "enabled": True,
            "priority": 30,
            "models": ["gpt-4o"],
            "protocols": ["chat_completions"],
            "capabilities": ["code"],
            "oauth_config": {
                "token_file": "/tmp/test_openai_token.json",
                "flow": "openai_deviceauth",
                "auth_url": "https://auth.openai.com/api/accounts/deviceauth/usercode",
                "poll_url": "https://auth.openai.com/api/accounts/deviceauth/token",
                "token_url": "https://auth.openai.com/oauth/token",
                "client_id": "app_test_client_id",
            },
        },
        "claude": {
            "type": "api_key",
            "name": "Anthropic Claude",
            "description": "Anthropic native API",
            "enabled": True,
            "priority": 53,
            "models": ["claude-sonnet-4.6"],
            "protocols": ["messages"],
            "capabilities": ["code"],
            "api_key": {
                "require_auth": True,
                "api_base_url": "https://api.anthropic.com",
                "api_key_env": "ANTHROPIC_API_KEY",
                "header_name": "x-api-key",
                "auth_scheme": "",
            },
        },
    }
}


@pytest.fixture
def providers_yaml(tmp_path):
    """Create a temporary providers.yaml for testing."""
    p = tmp_path / "providers.yaml"
    p.write_text(yaml.dump(SAMPLE_PROVIDERS, allow_unicode=True))
    return p


@pytest.fixture(autouse=True)
def patch_providers_path(providers_yaml):
    """Patch PROVIDERS_YAML to use temp file and clear shared OAuth flow state."""
    import api.v2.providers as pmod
    pmod._active_flows.clear()
    with patch("api.v2.providers.PROVIDERS_YAML", providers_yaml):
        yield providers_yaml
    pmod._active_flows.clear()


# ============================================================
# GET /api/v2/providers
# ============================================================

class TestListProviders:
    def test_returns_all_providers(self):
        resp = client.get("/api/v2/providers")
        assert resp.status_code == 200
        data = resp.json()
        ids = {p["id"] for p in data}
        assert ids == {"copilot", "openai", "claude"}

    def test_sorted_by_priority(self):
        resp = client.get("/api/v2/providers")
        data = resp.json()
        priorities = [p["priority"] for p in data]
        assert priorities == sorted(priorities)

    def test_oauth_token_is_masked(self):
        resp = client.get("/api/v2/providers")
        data = resp.json()
        copilot = next(p for p in data if p["id"] == "copilot")
        preview = copilot["auth_status"]["access_token_preview"]
        # Should not expose full token, must be masked
        assert preview is not None
        assert "gho_realtoken1234" not in preview
        assert preview.endswith("***")

    def test_api_key_has_status(self):
        resp = client.get("/api/v2/providers")
        data = resp.json()
        claude = next(p for p in data if p["id"] == "claude")
        assert "auth_status" in claude
        assert "has_key" in claude["auth_status"]

    def test_oauth_device_token_file_reported(self):
        resp = client.get("/api/v2/providers")
        data = resp.json()
        openai = next(p for p in data if p["id"] == "openai")
        assert openai["auth_status"]["token_file"] == "/tmp/test_openai_token.json"

    def test_oauth_device_has_token_false_when_no_file(self):
        resp = client.get("/api/v2/providers")
        data = resp.json()
        openai = next(p for p in data if p["id"] == "openai")
        assert openai["auth_status"]["has_token"] is False


# ============================================================
# GET /api/v2/providers/{id}
# ============================================================

class TestGetProvider:
    def test_get_existing_provider(self):
        resp = client.get("/api/v2/providers/copilot")
        assert resp.status_code == 200
        assert resp.json()["id"] == "copilot"

    def test_get_missing_provider_returns_404(self):
        resp = client.get("/api/v2/providers/nonexistent")
        assert resp.status_code == 404


# ============================================================
# POST /api/v2/providers/{id}/toggle
# ============================================================

class TestToggleProvider:
    def test_toggle_disables_enabled_provider(self, providers_yaml):
        resp = client.post("/api/v2/providers/copilot/toggle")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Verify persisted
        data = yaml.safe_load(providers_yaml.read_text())
        assert data["providers"]["copilot"]["enabled"] is False

    def test_toggle_enables_disabled_provider(self, providers_yaml):
        # Disable first
        client.post("/api/v2/providers/copilot/toggle")
        # Enable again
        resp = client.post("/api/v2/providers/copilot/toggle")
        assert resp.json()["enabled"] is True

    def test_toggle_missing_provider_returns_404(self):
        resp = client.post("/api/v2/providers/unknown/toggle")
        assert resp.status_code == 404


# ============================================================
# POST /api/v2/providers/{id}/config (api_key type)
# ============================================================

class TestSaveApiKeyConfig:
    def test_save_api_key(self, providers_yaml):
        resp = client.post(
            "/api/v2/providers/claude/config",
            json={"key_value": "sk-ant-testapikey12345"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        # Verify persisted
        data = yaml.safe_load(providers_yaml.read_text())
        assert data["providers"]["claude"]["api_key"]["key_value"] == "sk-ant-testapikey12345"

    def test_save_api_key_with_base_url(self, providers_yaml):
        resp = client.post(
            "/api/v2/providers/claude/config",
            json={"key_value": "sk-ant-testkey", "api_base_url": "https://custom.api.com"},
        )
        assert resp.status_code == 200
        data = yaml.safe_load(providers_yaml.read_text())
        assert data["providers"]["claude"]["api_key"]["api_base_url"] == "https://custom.api.com"

    def test_save_config_for_non_api_key_provider_returns_400(self):
        resp = client.post(
            "/api/v2/providers/copilot/config",
            json={"key_value": "some-key"},
        )
        assert resp.status_code == 400

    def test_save_config_missing_provider_returns_404(self):
        resp = client.post(
            "/api/v2/providers/nonexistent/config",
            json={"key_value": "some-key"},
        )
        assert resp.status_code == 404


# ============================================================
# POST /api/v2/providers/{id}/oauth/start
# ============================================================

class TestStartOAuthFlow:
    def test_start_oauth_code_flow_returns_auth_url(self):
        resp = client.post("/api/v2/providers/copilot/oauth/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow"] == "code"
        assert "auth_url" in data
        assert "github.com/login/oauth/authorize" in data["auth_url"]
        assert "state" in data

    def test_start_device_flow_calls_auth_endpoint(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "device_code": "test_device_code",
            "user_code": "ABCD-1234",
            "verification_uri": "https://auth.openai.com/device",
            "expires_in": 300,
            "interval": 5,
        }

        with patch("api.v2.providers.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            resp = client.post("/api/v2/providers/openai/oauth/start")

        assert resp.status_code == 200
        data = resp.json()
        assert data["flow"] == "device"
        assert data["user_code"] == "ABCD-1234"
        assert data["verification_uri"] == "https://auth.openai.com/device"
        assert data["expires_in"] == 300

    def test_start_oauth_for_api_key_provider_returns_400(self):
        resp = client.post("/api/v2/providers/claude/oauth/start")
        assert resp.status_code == 400

    def test_start_oauth_missing_provider_returns_404(self):
        resp = client.post("/api/v2/providers/nonexistent/oauth/start")
        assert resp.status_code == 404


# ============================================================
# GET /api/v2/providers/{id}/oauth/poll
# ============================================================

class TestPollOAuthFlow:
    def test_poll_with_no_active_flow(self):
        resp = client.get("/api/v2/providers/openai/oauth/poll")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_active_flow"

    def test_poll_returns_pending_when_waiting(self):
        from api.v2.providers import _active_flows
        import time

        _active_flows["openai"] = {
            "type": "device",
            "device_code": "test_dc",
            "provider_id": "openai",
            "poll_url": "https://auth.openai.com/api/accounts/deviceauth/token",
            "client_id": "app_test",
            "token_file": "",
            "interval": 0,
            "expires_at": time.time() + 300,
            "last_poll": 0.0,
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "authorization_pending"}

        with patch("api.v2.providers.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            resp = client.get("/api/v2/providers/openai/oauth/poll")

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

        # Cleanup
        _active_flows.pop("openai", None)


# ============================================================
# _mask helper
# ============================================================

class TestMaskHelper:
    def test_masks_long_secret(self):
        from api.v2.providers import _mask
        result = _mask("gho_realtoken1234567890")
        assert result == "gho_real***"

    def test_short_value_returns_stars(self):
        from api.v2.providers import _mask
        result = _mask("abc")
        assert result == "***"

    def test_none_returns_none(self):
        from api.v2.providers import _mask
        assert _mask(None) is None
        assert _mask("") is None

    def test_env_var_reference_shown_as_is(self):
        from api.v2.providers import _mask
        assert _mask("${SOME_VAR}") == "${SOME_VAR}"
