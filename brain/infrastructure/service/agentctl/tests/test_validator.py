from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config.validator import validate_agents_registry
from services.config_generator import generate_runtime_manifest


class ValidatorTests(unittest.TestCase):
    def test_running_agent_with_runtime_manifest_is_valid_without_agent_type(self) -> None:
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

            cfg = {
                "groups": {
                    "brain": [
                        {
                            "name": "tmp-agent-gemini-cli",
                            "group": "brain",
                            "role": "dev",
                            "path": td,
                            "tmux_session": "tmp-agent-gemini-cli",
                            "required": False,
                            "desired_state": "running",
                            "status": "active",
                        }
                    ]
                }
            }

            self.assertEqual(validate_agents_registry(cfg), [])


if __name__ == "__main__":
    unittest.main()
