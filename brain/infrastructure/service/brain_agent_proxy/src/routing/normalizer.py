"""Request normalizer."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class NormalizedRequest(BaseModel):
    """Normalized request structure."""
    model: str
    messages: List[Any] = []
    temperature: float = 1.0
    max_tokens: Optional[int] = None
    tools: Optional[List[Any]] = None
    stream: bool = False
    metadata: Dict[str, Any] = {}

    # Original request data
    original_request: Dict[str, Any] = {}


class Normalizer:
    """Normalize requests from different protocols to unified format."""

    @staticmethod
    def normalize_messages_request(body: Dict[str, Any]) -> NormalizedRequest:
        """Normalize Anthropic messages request."""
        return NormalizedRequest(
            model=body.get("model", ""),
            messages=body.get("messages", []),
            temperature=body.get("temperature", 1.0),
            max_tokens=body.get("max_tokens"),
            stream=body.get("stream", False),
            metadata={
                "system": body.get("system"),
                "tools": body.get("tools"),
            },
            original_request=body,
        )

    @staticmethod
    def normalize_chat_completions_request(body: Dict[str, Any]) -> NormalizedRequest:
        """Normalize OpenAI chat completions request."""
        return NormalizedRequest(
            model=body.get("model", ""),
            messages=body.get("messages", []),
            temperature=body.get("temperature", 1.0),
            max_tokens=body.get("max_tokens"),
            stream=body.get("stream", False),
            metadata={
                "top_p": body.get("top_p"),
                "tools": body.get("tools"),
            },
            original_request=body,
        )

    @staticmethod
    def normalize_responses_request(body: Dict[str, Any]) -> NormalizedRequest:
        """Normalize OpenAI responses request."""
        # Parse input (can be messages or text)
        input_data = body.get("input", [])
        messages = []
        for item in input_data:
            if isinstance(item, dict):
                if item.get("type") == "message":
                    messages.append(item.get("content", ""))
                elif item.get("type") == "text":
                    messages.append(item.get("text", ""))

        return NormalizedRequest(
            model=body.get("model", ""),
            messages=messages,
            temperature=body.get("temperature", 1.0),
            max_tokens=body.get("max_tokens"),
            stream=body.get("stream", False),
            metadata={
                "input": input_data,
                "tools": body.get("tools"),
            },
            original_request=body,
        )
