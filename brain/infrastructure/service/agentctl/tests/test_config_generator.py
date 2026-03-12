from __future__ import annotations

from pathlib import Path
import sys
import json
import tempfile
import unittest
from unittest.mock import patch


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from services.config_generator import (
    _build_settings_env,
    generate_all_configs,
    generate_runtime_manifest,
    runtime_manifest_path,
)


class ConfigGeneratorTests(unittest.TestCase):
    def test_proxy_uses_8210_and_canonical_auth_token(self) -> None:
        spec = {
            "name": "agent-system-pmo",
            "model": "claude-sonnet-4.6",
            "transport_mode": "proxy",
        }

        with patch.dict("os.environ", {"BRAIN_PROXY_BASE_URL": "http://127.0.0.1:8210"}, clear=False):
            env = _build_settings_env("copilot", spec)

        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8210")
        self.assertEqual(
            env["ANTHROPIC_AUTH_TOKEN"],
            "bgw-apx-v1--p-copilot--m-claude_sonnet_4_6--n-agent_system_pmo",
        )
        self.assertEqual(env["ANTHROPIC_MODEL"], "copilot/claude-sonnet-4.6")

    def test_proxy_transport_defaults_to_8210(self) -> None:
        spec = {
            "name": "agent-system-pmo",
            "model": "claude-sonnet-4.6",
            "transport_mode": "proxy",
        }

        with patch.dict("os.environ", {}, clear=False):
            env = _build_settings_env("copilot", spec)

        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8210")

    def test_default_transport_uses_proxy_base_url(self) -> None:
        spec = {
            "name": "agent-system-pmo",
            "model": "claude-sonnet-4.6",
        }

        with patch.dict("os.environ", {"BRAIN_PROXY_BASE_URL": "http://127.0.0.1:8210"}, clear=False):
            env = _build_settings_env("copilot", spec)

        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8210")

    def test_generate_runtime_manifest_persists_launch_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec = {
                "name": "tmp-agent-gemini-cli",
                "agent_type": "gemini",
                "cli_type": "native",
                "cwd": td,
                "model": "gemini-2.5-pro",
                "env": {"GEMINI_API_KEY": "${GEMINI_API_KEY}"},
            }

            path = generate_runtime_manifest(spec)

            self.assertEqual(path, str(runtime_manifest_path(td)))
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(payload["runtime"]["command"], "gemini")
            self.assertEqual(payload["runtime"]["args"], ["--model", "gemini-2.5-pro"])
            self.assertEqual(payload["runtime"]["env"]["GEMINI_API_KEY"], "${GEMINI_API_KEY}")

    def test_generate_all_configs_uses_path_and_existing_runtime_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "tmp-agent-gemini-cli",
                    "agent_type": "gemini",
                    "cli_type": "native",
                    "cwd": td,
                    "model": "gemini-2.5-pro",
                }
            )

            result = generate_all_configs(
                {
                    "name": "tmp-agent-gemini-cli",
                    "path": td,
                    "role": "dev",
                    "group": "brain",
                }
            )

            self.assertEqual(result["runtime_manifest"], str(runtime_manifest_path(td)))
            self.assertNotIn("settings_local", result)

    def test_generate_all_configs_recovers_model_from_runtime_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "tmp-agent-copilot",
                    "agent_type": "copilot",
                    "cwd": td,
                    "model": "copilot/gpt-5-mini",
                    "cli_args": ["--dangerously-skip-permissions"],
                    "env": {"BRAIN_TRANSPORT_MODE": "proxy"},
                }
            )

            with patch.dict("os.environ", {"BRAIN_PROXY_BASE_URL": "http://127.0.0.1:8210"}, clear=False):
                result = generate_all_configs(
                    {
                        "name": "tmp-agent-copilot",
                        "path": td,
                        "role": "dev",
                        "group": "brain",
                    }
                )

            settings = json.loads(Path(result["settings_local"]).read_text(encoding="utf-8"))
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8210")
            self.assertEqual(settings["env"]["ANTHROPIC_MODEL"], "copilot/gpt-5-mini")

    def test_generate_all_configs_preserves_cli_args_from_runtime_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            generate_runtime_manifest(
                {
                    "name": "tmp-agent-copilot",
                    "agent_type": "copilot",
                    "cwd": td,
                    "model": "copilot/gpt-5-mini",
                    "cli_args": ["--dangerously-skip-permissions"],
                }
            )

            generate_all_configs(
                {
                    "name": "tmp-agent-copilot",
                    "path": td,
                    "role": "dev",
                    "group": "brain",
                }
            )

            payload = json.loads(Path(runtime_manifest_path(td)).read_text(encoding="utf-8"))
            self.assertEqual(
                payload["runtime"]["args"],
                ["--model", "copilot/gpt-5-mini", "--dangerously-skip-permissions"],
            )


if __name__ == "__main__":
    unittest.main()
