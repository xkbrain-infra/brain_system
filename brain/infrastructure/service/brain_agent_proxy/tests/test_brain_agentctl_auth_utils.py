"""Tests for brain_agentctl OAuth helper utilities."""
import importlib.machinery
import importlib.util
from unittest.mock import patch
import unittest


def _load_brain_agentctl_module():
    path = "/brain/infrastructure/service/brain_agent_proxy/bin/brain_agentctl"
    loader = importlib.machinery.SourceFileLoader("brain_agentctl_module", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


brain_agentctl = _load_brain_agentctl_module()


class TestBrainAgentctlAuthUtils(unittest.TestCase):
    def test_token_status_missing(self):
        status, ttl = brain_agentctl._token_status(None)
        self.assertEqual(status, "missing")
        self.assertEqual(ttl, 0)

    def test_token_status_expired(self):
        status, ttl = brain_agentctl._token_status({"access_token": "abc", "expires_at": 1})
        self.assertEqual(status, "expired")
        self.assertEqual(ttl, 0)

    def test_token_status_valid_without_expiry(self):
        status, ttl = brain_agentctl._token_status({"access_token": "abc"})
        self.assertEqual(status, "valid")
        self.assertEqual(ttl, 0)

    def test_can_use_local_callback(self):
        self.assertTrue(brain_agentctl._can_use_local_callback("http://127.0.0.1:8085/oauth2callback"))
        self.assertTrue(brain_agentctl._can_use_local_callback("http://localhost:8085/callback"))
        self.assertFalse(brain_agentctl._can_use_local_callback("https://localhost:8085/callback"))
        self.assertFalse(brain_agentctl._can_use_local_callback("http://example.com/callback"))

    def test_api_key_status_reads_secrets_env_file(self):
        pdata = {"api_key": {"api_key_env": "MINIMAX_API_KEY"}}
        with patch.object(brain_agentctl, "_load_secrets_env", return_value={"MINIMAX_API_KEY": "secret"}):
            status, _ = brain_agentctl._api_key_status("minimax", pdata)
        self.assertEqual(status, "configured(secrets:MINIMAX_API_KEY)")

    def test_openai_runtime_status_uses_api_key_fallback_env(self):
        pdata = {"oauth_config": {"token_file": "~/.tmp/openai.json"}}
        with patch.object(brain_agentctl, "_read_token_file", return_value=None):
            with patch.object(brain_agentctl, "_load_secrets_env", return_value={"OPENAI_API_KEY": "sk-test"}):
                status = brain_agentctl._provider_runtime_status("openai", pdata)
        self.assertEqual(status["oauth"]["status"], "missing")
        self.assertEqual(status["api_key"]["status"], "configured(secrets:OPENAI_API_KEY)")


if __name__ == "__main__":
    unittest.main()
