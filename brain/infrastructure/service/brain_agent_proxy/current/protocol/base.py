"""Protocol handler base classes."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel


class Message(BaseModel):
    """Chat message."""
    role: str
    content: str
    name: Optional[str] = None
    tool_calls: Optional[Any] = None
    tool_call_id: Optional[str] = None


class Tool(BaseModel):
    """Tool definition."""
    name: str
    description: str
    input_schema: Dict[str, Any]


class NormalizedRequest(BaseModel):
    """Normalized request structure."""
    model: str
    messages: list[Message] = []
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: Optional[list[Tool]] = None
    stream: bool = False
    metadata: Dict[str, Any] = {}

    # Original request data
    original_request: Dict[str, Any] = {}


class ProtocolHandler(ABC):
    """Base class for protocol handlers."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Protocol name."""
        pass

    @abstractmethod
    def parse_request(self, body: Dict[str, Any]) -> NormalizedRequest:
        """Parse request into normalized format."""
        pass

    @abstractmethod
    def format_response(self, normalized_response: Dict[str, Any]) -> Dict[str, Any]:
        """Format normalized response back to protocol format."""
        pass

    @abstractmethod
    def format_error(self, error: Exception) -> Dict[str, Any]:
        """Format error response."""
        pass
