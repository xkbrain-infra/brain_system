"""Tests for Gemini OAuth token refresh behavior."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers.gemini import GeminiProvider


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class TestGeminiOAuthRefresh(unittest.TestCase):
    def test_refresh_oauth_token_updates_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "gemini.json"
            provider = GeminiProvider(
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_token_url="https://oauth2.googleapis.com/token",
            )

            with patch("src.providers.gemini.httpx.post") as mock_post:
                mock_post.return_value = _FakeResponse(
                    200,
                    {
                        "access_token": "new-access-token",
                        "refresh_token": "new-refresh-token",
                        "token_type": "Bearer",
                        "scope": "scope-a",
                        "expires_in": 1200,
                    },
                )
                token = provider._refresh_oauth_token(
                    {"refresh_token": "old-refresh-token", "scope": "scope-a"},
                    token_file,
                )

            self.assertEqual(token, "new-access-token")
            self.assertTrue(token_file.exists())
            with open(token_file) as f:
                saved = json.load(f)
            self.assertEqual(saved.get("access_token"), "new-access-token")
            self.assertEqual(saved.get("refresh_token"), "new-refresh-token")
            self.assertGreater(int(saved.get("expires_at", 0) or 0), 0)

    def test_resolve_oauth_bearer_refreshes_expired_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "gemini.json"
            with open(token_file, "w") as f:
                json.dump(
                    {
                        "access_token": "expired-token",
                        "refresh_token": "refresh-token",
                        "expires_at": 1,
                    },
                    f,
                )

            provider = GeminiProvider(
                oauth_token_file=str(token_file),
                oauth_client_id="client-id",
            )

            with patch.object(provider, "_refresh_oauth_token", return_value="fresh-token"):
                with patch.object(GeminiProvider, "_resolve_gcloud_adc_token", return_value=""):
                    token = provider._resolve_oauth_bearer()

            self.assertEqual(token, "fresh-token")


if __name__ == "__main__":
    unittest.main()
