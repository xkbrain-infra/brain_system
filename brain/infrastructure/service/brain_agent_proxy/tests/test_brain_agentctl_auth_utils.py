"""Tests for brain_agentctl OAuth helper utilities."""
import importlib.machinery
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
