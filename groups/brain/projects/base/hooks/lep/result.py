#!/usr/bin/env python3
"""LEP Engine - Result Types and Data Classes"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class CheckStatus(Enum):
    """Status of a gate check"""
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class CheckResult:
    """Result of a gate check"""
    status: CheckStatus
    gate_id: Optional[str] = None
    message: Optional[str] = None
    matched_pattern: Optional[str] = None
    priority: str = "MEDIUM"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_block(self) -> bool:
        """Check if this is a blocking result"""
        return self.status == CheckStatus.BLOCK

    @property
    def is_warn(self) -> bool:
        """Check if this is a warning result"""
        return self.status == CheckStatus.WARN

    @property
    def is_pass(self) -> bool:
        """Check if this check passed"""
        return self.status == CheckStatus.PASS

    @classmethod
    def block(cls, gate_id: str, message: str, priority: str = "CRITICAL") -> "CheckResult":
        """Create a blocking result"""
        return cls(
            status=CheckStatus.BLOCK,
            gate_id=gate_id,
            message=message,
            priority=priority
        )

    @classmethod
    def warn(cls, gate_id: str, message: str, priority: str = "MEDIUM") -> "CheckResult":
        """Create a warning result"""
        return cls(
            status=CheckStatus.WARN,
            gate_id=gate_id,
            message=message,
            priority=priority
        )

    @classmethod
    def pass_check(cls) -> "CheckResult":
        """Create a passing result"""
        return cls(status=CheckStatus.PASS)


@dataclass
class GateMatch:
    """A gate that applies to the current operation"""
    gate_id: str
    gate_spec: Dict[str, Any]
    enforcement: Dict[str, Any]
    priority: str
    checker_type: str


@dataclass
class CheckContext:
    """Context passed to checkers"""
    tool_name: str
    tool_input: Dict[str, Any]
    gate_id: str
    enforcement: Dict[str, Any]
    file_path: str = ""
    command: str = ""
    # Role context (injected by agentctl via env vars)
    agent_name: str = ""
    agent_role: str = "default"
    agent_group: str = ""
    scope_path: str = "/brain"


__all__ = [
    "CheckStatus",
    "CheckResult",
    "GateMatch",
    "CheckContext",
]
