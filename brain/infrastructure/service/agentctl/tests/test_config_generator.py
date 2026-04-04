import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/agentctl")
import services.config_generator as config_generator


class ConfigGeneratorTest(unittest.TestCase):
    def test_generate_runtime_manifest_normalizes_anthropic_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "name": "agent-demo",
                "cwd": tmpdir,
                "path": tmpdir,
                "agent_type": "anthropic",
                "model": "claude-sonnet-4-6",
            }

            runtime_path = config_generator.generate_runtime_manifest(spec)
            payload = json.loads(Path(runtime_path).read_text(encoding="utf-8"))

            self.assertEqual(payload["runtime"]["command"], "claude")
            self.assertEqual(payload["runtime"]["agent_type"], "claude")

    def test_agent_tmux_session_normalizes_plain_sandbox_session_name(self) -> None:
        spec = {
            "sandbox_id": "abc123",
            "tmux_session": "agent-demo",
            "env": {
                "IS_SANDBOX": "1",
                "BRAIN_SANDBOX_ID": "abc123",
            },
        }

        self.assertEqual(
            config_generator._agent_tmux_session("agent-demo", spec),
            "sbx_abc123__agent-demo",
        )

    def test_generate_mcp_config_uses_sandbox_bundle_and_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "cli_type": "claude",
                "sandbox_id": "abc123",
                "tmux_session": "sbx_abc123__agent-demo",
                "env": {
                    "IS_SANDBOX": "1",
                    "BRAIN_SANDBOX_ID": "abc123",
                },
            }

            config_generator.generate_mcp_config("agent-demo", "minimax", tmpdir, spec)

            payload = json.loads((Path(tmpdir) / ".mcp.json").read_text(encoding="utf-8"))
            servers = payload["mcpServers"]
            self.assertEqual(
                servers["mcp-brain_ipc"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain_ipc_c",
            )
            self.assertEqual(
                servers["mcp-brain_google_api"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain-google-api",
            )
            self.assertEqual(
                servers["mcp-brain_task_manager"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain_task_manager",
            )
            self.assertEqual(
                servers["mcp-brain_ipc"]["env"]["BRAIN_TMUX_SESSION"],
                "sbx_abc123__agent-demo",
            )

    def test_generate_settings_local_keeps_host_paths_for_non_sandbox_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "name": "agent-demo",
                "cwd": tmpdir,
                "path": tmpdir,
                "agent_type": "minimax",
                "tmux_session": "agent-demo",
                "transport_mode": "proxy",
                "env": {},
            }

            settings_path = config_generator._generate_settings_local(tmpdir, "orchestrator", "brain", spec)
            settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
            servers = settings["mcpServers"]
            self.assertEqual(servers["mcp-brain_ipc"]["command"], "/brain/bin/mcp/mcp-brain_ipc_c")
            self.assertEqual(
                servers["mcp-brain_google_api"]["command"],
                "/brain/bin/mcp/mcp-brain_google_api",
            )
            self.assertEqual(
                servers["mcp-brain_task_manager"]["command"],
                "/brain/infrastructure/service/brain_task_manager/bin/mcp-brain_task_manager",
            )
            self.assertEqual(servers["mcp-brain_ipc"]["env"]["BRAIN_TMUX_SESSION"], "agent-demo")
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8210")
            self.assertIn("ANTHROPIC_AUTH_TOKEN", settings["env"])
            self.assertNotIn("BRAIN_ENABLED_SKILLS", settings["env"])

    def test_generate_settings_local_uses_sandbox_bundle_for_sandbox_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "name": "agent-demo",
                "cwd": tmpdir,
                "path": tmpdir,
                "agent_type": "minimax",
                "tmux_session": "sbx_abc123__agent-demo",
                "sandbox_id": "abc123",
                "transport_mode": "proxy",
                "hooks": ["pre_tool_use", "post_tool_use"],
                "env": {
                    "IS_SANDBOX": "1",
                    "BRAIN_SANDBOX_ID": "abc123",
                },
            }

            settings_path = config_generator._generate_settings_local(tmpdir, "orchestrator", "brain", spec)
            settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
            servers = settings["mcpServers"]
            self.assertEqual(
                servers["mcp-brain_ipc"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain_ipc_c",
            )
            self.assertEqual(
                servers["mcp-brain_google_api"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain-google-api",
            )
            self.assertEqual(
                servers["mcp-brain_task_manager"]["command"],
                "/xkagent_infra/runtime/sandbox/_services/bin/mcp/mcp-brain_task_manager",
            )
            self.assertEqual(
                servers["mcp-brain_ipc"]["env"]["BRAIN_TMUX_SESSION"],
                "sbx_abc123__agent-demo",
            )
            self.assertEqual(
                settings["env"]["ANTHROPIC_BASE_URL"],
                "http://host.docker.internal:8210",
            )
            self.assertIn("ANTHROPIC_AUTH_TOKEN", settings["env"])
            self.assertNotIn("BRAIN_ENABLED_SKILLS", settings["env"])
            hooks = settings["hooks"]
            self.assertEqual(
                hooks["PreToolUse"][0]["hooks"][0]["command"],
                "/xkagent_infra/runtime/sandbox/_services/base/hooks/pre_tool_use",
            )
            self.assertEqual(
                hooks["PreToolUse"][0]["hooks"][0]["env"]["HOOK_ROOT"],
                "/xkagent_infra/runtime/sandbox/_services/base/hooks",
            )

    def test_generate_claude_md_rewrites_core_paths_for_sandbox_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "name": "agent-demo",
                "cwd": tmpdir,
                "path": tmpdir,
                "agent_type": "minimax",
                "sandbox_id": "abc123",
                "env": {
                    "IS_SANDBOX": "1",
                    "BRAIN_SANDBOX_ID": "abc123",
                },
            }

            output = config_generator.generate_claude_md(
                "agent-demo",
                "orchestrator",
                "brain",
                spec,
                force=True,
            )

            payload = Path(output).read_text(encoding="utf-8")
            self.assertIn("/xkagent_infra/runtime/sandbox/_services/INIT.yaml", payload)
            self.assertIn("/xkagent_infra/runtime/sandbox/_services/base/spec/core/lep.yaml", payload)
            self.assertIn("/xkagent_infra/runtime/sandbox/_services/base/knowledge/architecture/ipc_guide.md", payload)
            self.assertNotIn("/brain/INIT.yaml", payload)
            self.assertNotIn("/brain/base/spec/core/lep.yaml", payload)

    def test_generate_runtime_manifest_does_not_inject_managed_skill_prompt_for_claude_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = {
                "name": "agent-demo",
                "cwd": tmpdir,
                "path": tmpdir,
                "agent_type": "minimax",
                "cli_type": "claude",
                "_skill_bindings": {
                    "source": "/tmp/skill_bindings.yaml",
                    "resolved_skills": ["lep", "ipc"],
                    "role_skills": ["lep", "ipc"],
                    "agent_skills": [],
                    "workflow_skills": [],
                },
                "_lep_bindings": {
                    "source": "/tmp/lep_bindings.yaml",
                    "resolved_lep_profiles": [],
                    "role_lep_profiles": [],
                    "agent_lep_profiles": [],
                    "workflow_lep_profiles": [],
                },
            }

            runtime_path = config_generator.generate_runtime_manifest(spec)
            payload = json.loads(Path(runtime_path).read_text(encoding="utf-8"))

            self.assertEqual(payload["runtime"]["command"], "claude")
            self.assertEqual(payload["runtime"]["args"], ["--dangerously-skip-permissions"])
            self.assertEqual(payload["runtime"]["env"], {})


if __name__ == "__main__":
    unittest.main()
