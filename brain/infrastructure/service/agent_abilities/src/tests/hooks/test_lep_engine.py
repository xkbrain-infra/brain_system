#!/usr/bin/env python3
"""Unit tests for LepEngine"""

import sys
from pathlib import Path

# Add modules to path
AGENT_ABILITIES_SRC = Path(__file__).parent.parent.parent  # -> src/
sys.path.insert(0, str(AGENT_ABILITIES_SRC / "hooks" / "lep"))

import pytest
from engine import LepEngine, PRIORITY_ORDER
from result import CheckStatus, CheckResult
from lep import load_lep, LepConfig


class TestLepEngineInitialization:
    """Test engine initialization"""

    def test_engine_init_with_default_config(self):
        """Engine should initialize with default LEP config"""
        engine = LepEngine()
        assert engine is not None
        assert engine.config is not None
        assert isinstance(engine.config, LepConfig)

    def test_engine_init_with_custom_config(self):
        """Engine should accept custom config"""
        custom_config = LepConfig(
            actions={'write': ['create']},
            gates={'TEST-GATE': {}},
            command_mapping=None
        )
        engine = LepEngine(custom_config)
        assert engine.config == custom_config

    def test_engine_builds_checker_registry(self):
        """Engine should build checker registry from config"""
        engine = LepEngine()
        # Should have registered checkers for gates with enforcement
        assert hasattr(engine, '_checker_registry')
        assert isinstance(engine._checker_registry, dict)


class TestGateMatching:
    """Test gate matching logic"""

    @pytest.fixture
    def test_config(self):
        """Minimal test configuration"""
        return LepConfig(
            actions={'write': ['create']},
            gates={
                'TEST-WRITE-GATE': {
                    'enforcement': {
                        'stage': 'pre_tool_use',
                        'method': 'inline',
                        'triggers': {'tools': ['Write']},
                        'priority': 'HIGH'
                    }
                },
                'TEST-BASH-GATE': {
                    'enforcement': {
                        'stage': 'pre_tool_use',
                        'method': 'inline',
                        'triggers': {'tools': ['Bash']},
                        'priority': 'MEDIUM'
                    }
                }
            },
            command_mapping=None
        )

    def test_match_gates_by_tool(self, test_config):
        """Should match gates by tool name"""
        engine = LepEngine(test_config)
        matches = engine._match_gates("Write", {"file_path": "/test.txt"})

        assert len(matches) > 0
        assert any(m.gate_id == "TEST-WRITE-GATE" for m in matches)
        assert not any(m.gate_id == "TEST-BASH-GATE" for m in matches)

    def test_match_gates_priority_ordering(self, test_config):
        """Matched gates should be sorted by priority"""
        # Add a CRITICAL gate
        test_config.gates['TEST-CRITICAL-GATE'] = {
            'enforcement': {
                'stage': 'pre_tool_use',
                'method': 'inline',
                'triggers': {'tools': ['Write']},
                'priority': 'CRITICAL'
            }
        }

        engine = LepEngine(test_config)
        matches = engine._match_gates("Write", {"file_path": "/test.txt"})

        # CRITICAL should come before HIGH
        priorities = [m.priority for m in matches]
        assert priorities == sorted(priorities, key=lambda p: PRIORITY_ORDER.get(p, 99))

    def test_no_match_when_tool_not_in_triggers(self, test_config):
        """Should not match gates when tool doesn't match"""
        engine = LepEngine(test_config)
        matches = engine._match_gates("Read", {"file_path": "/test.txt"})

        # Read is not in any triggers, so no matches
        assert len(matches) == 0


class TestCheckExecution:
    """Test check execution logic"""

    @pytest.fixture
    def minimal_config_path(self):
        """Path to minimal test config"""
        return Path(__file__).parent / "fixtures" / "lep_minimal.yaml"

    def test_check_returns_pass_for_safe_operation(self, minimal_config_path):
        """Safe operations should pass"""
        config = load_lep(str(minimal_config_path))
        engine = LepEngine(config)

        result = engine.check("Write", {"file_path": "/safe/file.txt"})
        assert result.status == CheckStatus.PASS

    def test_check_returns_block_for_forbidden_pattern(self, minimal_config_path):
        """Forbidden patterns should block"""
        config = load_lep(str(minimal_config_path))
        engine = LepEngine(config)

        result = engine.check("Write", {"file_path": "/forbidden/file.txt"})
        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "TEST-BLOCK-GATE"
        assert "TEST BLOCK" in result.message

    def test_check_returns_warn_for_warning_pattern(self, minimal_config_path):
        """Warning patterns should warn"""
        config = load_lep(str(minimal_config_path))
        engine = LepEngine(config)

        result = engine.check("Write", {"file_path": "/warning/file.txt"})
        assert result.status == CheckStatus.WARN
        assert result.gate_id == "TEST-WARN-GATE"
        assert "TEST WARN" in result.message

    def test_first_block_wins(self, minimal_config_path):
        """First blocking result should win"""
        config = load_lep(str(minimal_config_path))
        # Add another blocking gate
        config.gates['TEST-BLOCK-GATE-2'] = {
            'enforcement': {
                'stage': 'pre_tool_use',
                'method': 'inline',
                'priority': 'LOW',  # Lower priority
                'triggers': {'tools': ['Write']},
                'patterns': {
                    'test': [{'pattern': 'forbidden', 'message': 'Gate 2'}]
                },
                'block_message': 'BLOCK 2'
            }
        }

        engine = LepEngine(config)
        result = engine.check("Write", {"file_path": "/forbidden/file.txt"})

        # Should return first block (higher priority CRITICAL gate)
        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "TEST-BLOCK-GATE"


class TestPatternMatching:
    """Test pattern matching utilities"""

    def test_matches_any_pattern_with_glob(self):
        """Should match glob patterns"""
        engine = LepEngine()

        patterns = ["*.txt", "/brain/**/*.yaml"]
        assert engine._matches_any_pattern("/test/file.txt", patterns)
        assert engine._matches_any_pattern("/brain/spec/test.yaml", patterns)
        assert not engine._matches_any_pattern("/test/file.py", patterns)

    def test_matches_any_command_with_regex(self):
        """Should match command regex patterns"""
        engine = LepEngine()

        patterns = ["rm.*-rf", "DROP\\s+TABLE"]
        assert engine._matches_any_command("rm -rf /tmp", patterns)
        assert engine._matches_any_command("DROP TABLE users", patterns)
        assert not engine._matches_any_command("ls -la", patterns)


class TestErrorHandling:
    """Test error handling and fail-safe behavior"""

    def test_engine_handles_missing_checker_gracefully(self):
        """Engine should skip gates without checkers"""
        config = LepConfig(
            actions={},
            gates={
                'GATE-WITHOUT-CHECKER': {
                    'enforcement': {
                        'stage': 'pre_tool_use',
                        'method': 'nonexistent_checker',
                        'triggers': {'tools': ['Write']}
                    }
                }
            },
            command_mapping=None
        )

        engine = LepEngine(config)
        result = engine.check("Write", {"file_path": "/test.txt"})

        # Should pass (skip the broken gate)
        assert result.status == CheckStatus.PASS

    def test_engine_handles_checker_exception_gracefully(self):
        """Engine should continue on checker exceptions"""
        # This is tested implicitly - engine catches exceptions in check()
        engine = LepEngine()
        result = engine.check("Write", {"file_path": "/test.txt"})

        # Should not raise exception
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
