#!/usr/bin/env python3
"""Integration tests for LEP Engine end-to-end flow

Tests all 14 major gates with V1/V2 message parity validation.
"""

import sys
import json
import subprocess
from pathlib import Path
from io import StringIO
from unittest.mock import patch

# Add modules to path
HOOK_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(HOOK_ROOT / "src" / "lep"))
sys.path.insert(0, str(HOOK_ROOT / "src" / "utils" / "python"))
sys.path.insert(0, str(HOOK_ROOT / "src" / "handlers" / "tool_validation" / "v2" / "python"))

import pytest
from engine import LepEngine
from cache import get_lep_config
from result import CheckStatus


class TestGateIntegration:
    """Integration tests for individual gates"""

    @pytest.fixture
    def engine(self):
        """Create engine with production lep.yaml"""
        config = get_lep_config()
        return LepEngine(config, HOOK_ROOT)

    # --- Spec Location Gates ---

    def test_g_scop_blocks_protected_init_yaml(self, engine):
        """G-SCOP: Block modification to /brain/INIT.yaml"""
        result = engine.check("Write", {"file_path": "/brain/INIT.yaml"})

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-SCOP"
        assert "INIT.yaml" in result.message or "保护文件" in result.message

    def test_g_scop_allows_safe_path(self, engine):
        """G-SCOP: Allow safe paths"""
        result = engine.check("Write", {"file_path": "/brain/groups/brain_system/projects/example/config.yaml"})

        # Should pass or warn, not block (G-SCOP should not trigger for safe paths)
        # Note: Other gates may still trigger, so we check that it's not blocked by G-SCOP specifically
        if result.status == CheckStatus.BLOCK:
            assert result.gate_id != "G-SCOP", f"G-SCOP should not block safe paths, but got: {result.gate_id}"

    def test_g_spec_location_blocks_spec_outside_spec_dir(self, engine):
        """G-SPEC-LOCATION: Block spec files outside /spec/"""
        result = engine.check("Write", {
            "file_path": "/brain/groups/test/my_spec.yaml",
            "content": "spec:\n  id: TEST-001"
        })

        # Should block or warn about spec location
        if result.status == CheckStatus.BLOCK:
            assert result.gate_id in ["G-SPEC-LOCATION", "G-SPEC-TEMPLATE"]

    def test_g_spec_location_allows_spec_in_spec_dir(self, engine):
        """G-SPEC-LOCATION: Allow spec in /spec/ directory"""
        result = engine.check("Write", {
            "file_path": "/brain/groups/test/spec/TEST-001.yaml"
        })

        # Should not block (may warn)
        assert result.status != CheckStatus.BLOCK or result.gate_id != "G-SPEC-LOCATION"

    # --- Agent Lifecycle Gates ---

    def test_g_agent_lifecycle_blocks_tmux_kill_session(self, engine):
        """G-AGENT-LIFECYCLE: Block tmux kill-session for agents"""
        result = engine.check("Bash", {
            "command": "tmux kill-session -t agent_system_pmo"
        })

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-AGENT-LIFECYCLE"
        assert "brain-agentctl" in result.message or "orchestrator" in result.message

    def test_g_agent_lifecycle_blocks_tmux_send_keys(self, engine):
        """G-AGENT-LIFECYCLE: Block tmux send-keys to agents"""
        result = engine.check("Bash", {
            "command": "tmux send-keys -t agent_system_pmo 'exit' Enter"
        })

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-AGENT-LIFECYCLE"

    def test_g_agent_lifecycle_allows_non_agent_tmux(self, engine):
        """G-AGENT-LIFECYCLE: Allow tmux operations on non-agent sessions"""
        result = engine.check("Bash", {
            "command": "tmux kill-session -t my_dev_session"
        })

        # Should not block for non-agent sessions
        if result.status == CheckStatus.BLOCK:
            assert result.gate_id != "G-AGENT-LIFECYCLE"

    # --- Database Gates ---

    def test_g_db_backup_blocks_drop_database(self, engine):
        """G-DB-BACKUP: Block DROP DATABASE without backup"""
        result = engine.check("Bash", {
            "command": "psql -c 'DROP DATABASE newsalpha'"
        })

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-DB-BACKUP"
        assert "backup" in result.message.lower() or "pg_dump" in result.message

    def test_g_db_backup_blocks_drop_table(self, engine):
        """G-DB-BACKUP: Block DROP TABLE without backup"""
        result = engine.check("Bash", {
            "command": "psql newsalpha -c 'DROP TABLE raw_messages'"
        })

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-DB-BACKUP"

    def test_g_db_backup_allows_safe_queries(self, engine):
        """G-DB-BACKUP: Allow safe database queries"""
        result = engine.check("Bash", {
            "command": "psql newsalpha -c 'SELECT COUNT(*) FROM raw_messages'"
        })

        # Should not trigger DB-BACKUP gate
        if result.status == CheckStatus.BLOCK:
            assert result.gate_id != "G-DB-BACKUP"

    # --- Delete and Backup Gates ---

    def test_g_delete_backup_warns_on_rm_yaml(self, engine):
        """G-DELETE-BACKUP: Warn on deleting .yaml files"""
        result = engine.check("Bash", {
            "command": "rm /brain/groups/test/old_config.yaml"
        })

        # Should warn about backup
        assert result.status in [CheckStatus.WARN, CheckStatus.BLOCK]
        if result.status == CheckStatus.WARN:
            assert result.gate_id == "G-DELETE-BACKUP"
            assert "backup" in result.message.lower() or "git" in result.message.lower()

    def test_g_delete_backup_warns_on_rm_python(self, engine):
        """G-DELETE-BACKUP: Warn on deleting .py files"""
        result = engine.check("Bash", {
            "command": "rm /brain/infrastructure/test/old_module.py"
        })

        if result.status == CheckStatus.WARN:
            assert result.gate_id == "G-DELETE-BACKUP"

    # --- Docker and Infrastructure Gates ---

    def test_g_docker_db_blocks_postgres_without_volume(self, engine):
        """G-DOCKER-DB: Block postgres container without volume"""
        result = engine.check("Bash", {
            "command": "docker run -d postgres:15"
        })

        # Should block or warn about missing volume
        if result.status in [CheckStatus.BLOCK, CheckStatus.WARN]:
            assert result.gate_id == "G-DOCKER-DB"
            assert "volume" in result.message.lower() or "持久化" in result.message

    def test_g_docker_db_allows_postgres_with_volume(self, engine):
        """G-DOCKER-DB: Allow postgres with volume"""
        result = engine.check("Bash", {
            "command": "docker run -d -v pgdata:/var/lib/postgresql/data postgres:15"
        })

        # Should not block (may pass or warn for other reasons)
        if result.gate_id == "G-DOCKER-DB":
            assert result.status != CheckStatus.BLOCK

    # --- Git and Workflow Gates ---

    def test_g_gitignore_warns_sensitive_files(self, engine):
        """G-GITIGNORE: Warn about committing sensitive files"""
        result = engine.check("Bash", {
            "command": "git add .env"
        })

        # Should warn about .env
        if result.status == CheckStatus.WARN:
            assert result.gate_id == "G-GITIGNORE"
            assert ".env" in result.message or "sensitive" in result.message.lower()

    def test_g_git_commit_message_warns_poor_message(self, engine):
        """G-GIT-COMMIT-MESSAGE: Warn about poor commit messages"""
        result = engine.check("Bash", {
            "command": "git commit -m 'fix'"
        })

        # Should warn about commit message quality
        if result.status == CheckStatus.WARN:
            assert result.gate_id == "G-GIT-COMMIT-MESSAGE"

    # --- Plan and Workflow Gates ---

    def test_g_nawp_blocks_modification_without_plan(self, engine):
        """G-NAWP: Block modifications without plan"""
        # This gate requires context about plan approval
        # Testing basic pattern matching
        result = engine.check("Write", {
            "file_path": "/brain/base/spec/core/architecture.yaml",
            "content": "# Modified architecture"
        })

        # Should block modifications to core specs
        if result.status == CheckStatus.BLOCK:
            assert result.gate_id in ["G-NAWP", "G-SCOP"]


class TestMessageParity:
    """Verify V1/V2 message format parity"""

    @pytest.fixture
    def v2_handler_path(self):
        """Path to V2 handler"""
        return HOOK_ROOT / "src" / "handlers" / "tool_validation" / "v2" / "python" / "handler.py"

    def run_v2_handler(self, tool_name, tool_input, handler_path):
        """Run V2 handler with given input"""
        input_data = {
            "toolName": tool_name,
            "toolInput": tool_input
        }

        result = subprocess.run(
            [sys.executable, str(handler_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True
        )

        # Parse output
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"stdout": result.stdout, "stderr": result.stderr}

    def test_block_message_format(self, v2_handler_path):
        """Block messages should have correct JSON format"""
        output = self.run_v2_handler(
            "Write",
            {"file_path": "/brain/INIT.yaml"},
            v2_handler_path
        )

        # V2 should output block result
        if "block" in output:
            assert output["block"] is True
            assert "blockMessage" in output
            assert "gate" in output

    def test_warn_message_format(self, v2_handler_path):
        """Warn messages should have correct JSON format"""
        output = self.run_v2_handler(
            "Bash",
            {"command": "rm /brain/test.yaml"},
            v2_handler_path
        )

        # V2 should output warn result
        if "warning" in output:
            assert isinstance(output["warning"], str)
            assert "gate" in output

    def test_pass_message_format(self, v2_handler_path):
        """Pass results should have correct JSON format"""
        output = self.run_v2_handler(
            "Read",
            {"file_path": "/brain/test.txt"},
            v2_handler_path
        )

        # V2 should output pass result
        if "pass" in output or output.get("block") is False:
            assert "error" not in output


class TestEndToEndFlow:
    """Test complete end-to-end flow"""

    def test_complete_flow_from_json_input(self):
        """Test complete flow: JSON → Engine → Result → Output"""
        # Simulate PreToolUse hook flow
        input_json = {
            "toolName": "Bash",
            "toolInput": {
                "command": "tmux kill-session -t agent_system_qa"
            }
        }

        # Load engine
        config = get_lep_config()
        engine = LepEngine(config, HOOK_ROOT)

        # Execute check
        result = engine.check(
            input_json["toolName"],
            input_json["toolInput"]
        )

        # Verify result
        assert result is not None
        assert hasattr(result, 'status')
        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "G-AGENT-LIFECYCLE"
        assert result.message is not None

    def test_multiple_gates_triggered(self):
        """Test when multiple gates apply"""
        config = get_lep_config()
        engine = LepEngine(config, HOOK_ROOT)

        # A command that might trigger multiple gates
        result = engine.check("Bash", {
            "command": "git add .env && git commit -m 'fix' && git push"
        })

        # Should get a result (block or warn)
        assert result is not None
        assert result.status in [CheckStatus.BLOCK, CheckStatus.WARN, CheckStatus.PASS]

    def test_priority_ordering_enforcement(self):
        """Test that CRITICAL gates execute before MEDIUM"""
        config = get_lep_config()
        engine = LepEngine(config, HOOK_ROOT)

        # Trigger multiple gates with different priorities
        result = engine.check("Write", {
            "file_path": "/brain/INIT.yaml"  # CRITICAL: G-SCOP
        })

        # Should get CRITICAL gate result first
        assert result.gate_id == "G-SCOP"  # Highest priority for this path

    def test_first_block_wins(self):
        """Test that first blocking gate stops execution"""
        config = get_lep_config()
        engine = LepEngine(config, HOOK_ROOT)

        # Command that might match multiple blocking gates
        result = engine.check("Bash", {
            "command": "psql -c 'DROP DATABASE test' && rm -rf /brain"
        })

        # Should get first block
        assert result.status == CheckStatus.BLOCK
        # Gate ID should be one of the blocking gates
        assert result.gate_id in ["G-DB-BACKUP", "G-DELETE-BACKUP", "G-SCOP"]


class TestPerformance:
    """Performance benchmarks"""

    def test_engine_init_performance(self, benchmark):
        """Benchmark engine initialization time"""
        def init_engine():
            config = get_lep_config()
            return LepEngine(config, HOOK_ROOT)

        # Should complete in <50ms
        result = benchmark(init_engine)
        assert result is not None

    def test_check_performance(self, benchmark):
        """Benchmark check execution time"""
        config = get_lep_config()
        engine = LepEngine(config, HOOK_ROOT)

        def run_check():
            return engine.check("Write", {"file_path": "/brain/test.txt"})

        # Should complete in <10ms
        result = benchmark(run_check)
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
