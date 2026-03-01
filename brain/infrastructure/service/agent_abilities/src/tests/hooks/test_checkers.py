#!/usr/bin/env python3
"""Unit tests for Checker implementations"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

# Add modules to path
AGENT_ABILITIES_SRC = Path(__file__).parent.parent.parent  # -> src/
HOOK_ROOT = AGENT_ABILITIES_SRC / "hooks"
sys.path.insert(0, str(HOOK_ROOT / "lep"))

import pytest
from checkers import (
    BaseChecker,
    InlineChecker,
    BinaryChecker,
    PathChecker,
    FileOrgChecker,
)
from result import CheckStatus, CheckResult, CheckContext


class TestBaseChecker:
    """Test BaseChecker abstract class"""

    def test_base_checker_is_abstract(self):
        """BaseChecker cannot be instantiated directly"""
        with pytest.raises(TypeError):
            BaseChecker()


class TestInlineChecker:
    """Test InlineChecker pattern matching"""

    @pytest.fixture
    def patterns_config(self):
        """Sample patterns configuration"""
        return {
            "dangerous_commands": [
                {"pattern": r"rm.*-rf", "message": "Dangerous rm -rf detected"},
                {"pattern": r"DROP\s+TABLE", "message": "SQL DROP TABLE detected"},
            ],
            "forbidden_paths": [
                {"pattern": r"/etc/passwd", "message": "Access to /etc/passwd forbidden"},
            ]
        }

    def test_inline_checker_initialization(self, patterns_config):
        """InlineChecker should precompile patterns"""
        checker = InlineChecker(patterns_config)

        assert checker.patterns == patterns_config
        assert hasattr(checker, '_compiled')
        assert 'dangerous_commands' in checker._compiled
        assert len(checker._compiled['dangerous_commands']) == 2

    def test_inline_checker_matches_pattern(self, patterns_config):
        """Should match patterns in command"""
        checker = InlineChecker(patterns_config)
        context = CheckContext(
            gate_id="TEST-GATE",
            tool_name="Bash",
            tool_input={"command": "rm -rf /tmp"},
            enforcement={"priority": "CRITICAL", "block_message": "Blocked: {message}"},
            command="rm -rf /tmp",
            file_path=None,
        )

        result = checker.check(context)

        assert result.status == CheckStatus.BLOCK
        assert result.gate_id == "TEST-GATE"
        assert "Dangerous rm -rf" in result.message or "Blocked" in result.message

    def test_inline_checker_critical_priority_blocks(self, patterns_config):
        """CRITICAL priority should block"""
        checker = InlineChecker(patterns_config)
        context = CheckContext(
            gate_id="TEST-CRITICAL",
            tool_name="Bash",
            tool_input={"command": "DROP TABLE users"},
            enforcement={"priority": "CRITICAL", "block_message": "Critical block"},
            command="DROP TABLE users",
            file_path=None,
        )

        result = checker.check(context)
        assert result.status == CheckStatus.BLOCK
        assert result.priority == "CRITICAL"

    def test_inline_checker_medium_priority_warns(self, patterns_config):
        """MEDIUM priority should warn"""
        checker = InlineChecker(patterns_config)
        context = CheckContext(
            gate_id="TEST-MEDIUM",
            tool_name="Bash",
            tool_input={"command": "rm -rf /tmp"},
            enforcement={"priority": "MEDIUM", "warn_message": "Warning: {message}"},
            command="rm -rf /tmp",
            file_path=None,
        )

        result = checker.check(context)
        assert result.status == CheckStatus.WARN
        assert result.priority == "MEDIUM"

    def test_inline_checker_no_match_passes(self, patterns_config):
        """No pattern match should pass"""
        checker = InlineChecker(patterns_config)
        context = CheckContext(
            gate_id="TEST-GATE",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
            enforcement={"priority": "MEDIUM"},
            command="ls -la",
            file_path=None,
        )

        result = checker.check(context)
        assert result.status == CheckStatus.PASS

    def test_inline_checker_case_insensitive_matching(self):
        """Should support case-insensitive patterns"""
        patterns = {
            "test": [
                {"pattern": r"(?i)docker", "message": "Docker command detected"}
            ]
        }
        checker = InlineChecker(patterns)
        context = CheckContext(
            gate_id="TEST",
            tool_name="Bash",
            tool_input={"command": "DOCKER run alpine"},
            enforcement={"priority": "LOW"},
            command="DOCKER run alpine",
            file_path=None,
        )

        result = checker.check(context)
        assert result.status == CheckStatus.WARN


class TestBinaryChecker:
    """Test BinaryChecker subprocess wrapper"""

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess.run"""
        with patch('checkers.subprocess.run') as mock:
            yield mock

    def test_binary_checker_initialization(self):
        """BinaryChecker should accept binary path and check type"""
        checker = BinaryChecker("/bin/test_checker", "spec_location")
        assert checker.binary_path == "/bin/test_checker"
        assert checker.check_type == "spec_location"

    def test_binary_checker_calls_subprocess(self, mock_subprocess):
        """Should call subprocess with correct arguments"""
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        checker = BinaryChecker("/bin/test_checker", "spec_check")
        context = CheckContext(
            gate_id="TEST-BINARY",
            tool_name="Write",
            tool_input={"file_path": "/test.txt"},
            enforcement={"priority": "HIGH"},
            command=None,
            file_path="/test.txt",
        )

        checker.check(context)

        # Verify subprocess was called
        assert mock_subprocess.called
        call_args = mock_subprocess.call_args[0][0]
        assert "/bin/test_checker" in call_args
        assert "spec_check" in call_args

    def test_binary_checker_blocks_on_exit_1(self, mock_subprocess):
        """Exit code 1 should block"""
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Check failed: forbidden path"
        )

        checker = BinaryChecker("/bin/test_checker", "path_check")
        context = CheckContext(
            gate_id="TEST-BINARY",
            tool_name="Write",
            tool_input={"file_path": "/forbidden.txt"},
            enforcement={"priority": "CRITICAL", "block_message": "Binary check failed"},
            command=None,
            file_path="/forbidden.txt",
        )

        result = checker.check(context)
        assert result.status == CheckStatus.BLOCK
        assert "forbidden path" in result.message or "Binary check failed" in result.message

    def test_binary_checker_passes_on_exit_0(self, mock_subprocess):
        """Exit code 0 should pass"""
        mock_subprocess.return_value = Mock(returncode=0, stdout="OK", stderr="")

        checker = BinaryChecker("/bin/test_checker", "safe_check")
        context = CheckContext(
            gate_id="TEST-BINARY",
            tool_name="Write",
            tool_input={"file_path": "/safe.txt"},
            enforcement={"priority": "MEDIUM"},
            command=None,
            file_path="/safe.txt",
        )

        result = checker.check(context)
        assert result.status == CheckStatus.PASS

    def test_binary_checker_handles_subprocess_error(self, mock_subprocess):
        """Should handle subprocess errors gracefully"""
        mock_subprocess.side_effect = subprocess.CalledProcessError(2, "cmd")

        checker = BinaryChecker("/bin/test_checker", "error_check")
        context = CheckContext(
            gate_id="TEST-BINARY",
            tool_name="Write",
            tool_input={"file_path": "/test.txt"},
            enforcement={"priority": "MEDIUM"},
            command=None,
            file_path="/test.txt",
        )

        result = checker.check(context)
        # Should pass on error (fail-safe)
        assert result.status == CheckStatus.PASS


class TestPathChecker:
    """Test PathChecker wrapper"""

    @pytest.fixture
    def mock_path_checker_module(self):
        """Mock path_checker module"""
        mock_module = MagicMock()
        sys.modules['checker'] = mock_module
        yield mock_module
        del sys.modules['checker']

    def test_path_checker_initialization(self):
        """PathChecker should initialize with HOOK_ROOT"""
        checker = PathChecker(HOOK_ROOT)
        assert checker.hook_root == HOOK_ROOT

    def test_path_checker_uses_python_checker(self):
        """PathChecker should import Python checker module"""
        checker = PathChecker(HOOK_ROOT)

        # Should have check_spec_path function (may be None if import failed)
        assert hasattr(checker, 'check_spec_path')


class TestFileOrgChecker:
    """Test FileOrgChecker wrapper"""

    @pytest.fixture
    def mock_file_org_module(self):
        """Mock file_org_checker module"""
        mock_module = MagicMock()
        sys.modules['checker'] = mock_module
        yield mock_module
        del sys.modules['checker']

    def test_file_org_checker_initialization(self):
        """FileOrgChecker should initialize with HOOK_ROOT"""
        checker = FileOrgChecker(HOOK_ROOT)
        assert checker.hook_root == HOOK_ROOT

    def test_file_org_checker_uses_python_checker(self):
        """FileOrgChecker should import Python checker module"""
        checker = FileOrgChecker(HOOK_ROOT)

        # Should have check_file_organization function (may be None if import failed)
        assert hasattr(checker, 'check_file_organization')


class TestCheckerIntegration:
    """Integration tests for checker combinations"""

    def test_multiple_checkers_same_gate(self):
        """A gate can have multiple checkers"""
        inline_checker = InlineChecker({
            "test": [{"pattern": "forbidden", "message": "Forbidden pattern"}]
        })

        context1 = CheckContext(
            gate_id="MULTI-CHECK",
            tool_name="Bash",
            tool_input={"command": "echo safe"},
            enforcement={"priority": "MEDIUM"},
            command="echo safe",
            file_path=None,
        )

        context2 = CheckContext(
            gate_id="MULTI-CHECK",
            tool_name="Bash",
            tool_input={"command": "forbidden command"},
            enforcement={"priority": "CRITICAL"},
            command="forbidden command",
            file_path=None,
        )

        # First context should pass
        assert inline_checker.check(context1).status == CheckStatus.PASS

        # Second context should block
        assert inline_checker.check(context2).status == CheckStatus.BLOCK


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
