"""Anthropic /v1/messages protocol handler."""
from typing import Any, Dict, List, Optional

from .base import (
    Message,
    NormalizedRequest,
    ProtocolHandler,
    Tool,
)


def _normalize_content(content: Any) -> str:
    """Normalize message content to string."""
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        ctype = content.get("type")
        if ctype == "text":
            return str(content.get("text", ""))
        if ctype == "thinking":
            return str(content.get("thinking", ""))
        if ctype == "image":
            src = content.get("source", {}) or {}
            media_type = src.get("media_type", "")
            data = src.get("data", "")
            return f"[image:{media_type}:{len(str(data))}]"
        if ctype == "tool_result":
            return _normalize_content(content.get("content", ""))
        return _normalize_content(content.get("content", ""))
    elif isinstance(content, list):
        parts = []
        for block in content:
            part = _normalize_content(block)
            if part:
                parts.append(part)
        return " ".join(parts)
    return str(content)


class MessagesProtocolHandler(ProtocolHandler):
    """Handler for Anthropic /v1/messages API."""

    @property
    def protocol_name(self) -> str:
        return "messages"

    def parse_request(self, body: Dict[str, Any]) -> NormalizedRequest:
        """Parse Anthropic messages request."""
        # Extract model
        model = body.get("model", "")

        # Parse messages
        messages = []
        for msg in body.get("messages", []):
            messages.append(Message(
                role=msg.get("role", "user"),
                content=_normalize_content(msg.get("content", "")),
                name=msg.get("name"),
            ))

        # Parse tools
        tools = None
        if "tools" in body:
            tools = [
                Tool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("input_schema", {}),
                )
                for t in body["tools"]
            ]

        return NormalizedRequest(
            model=model,
            messages=messages,
            temperature=body.get("temperature", 1.0),
            max_tokens=body.get("max_tokens"),
            tools=tools,
            stream=body.get("stream", False),
            metadata={
                "system": body.get("system"),
                "stop_reason": body.get("stop_reason"),
                "top_k": body.get("top_k"),
                "top_p": body.get("top_p"),
            },
            original_request=body,
        )

    def format_response(self, normalized_response: Dict[str, Any]) -> Dict[str, Any]:
        """Format response to Anthropic messages format."""
        content = normalized_response.get("content", "")
        # Anthropic Messages API expects content blocks, not plain string.
        if isinstance(content, list):
            content_blocks = content
        else:
            content_blocks = [{"type": "text", "text": str(content)}]

        usage = {
            "input_tokens": normalized_response.get("input_tokens", 0),
            "output_tokens": normalized_response.get("output_tokens", 0),
        }
        if normalized_response.get("cache_read_input_tokens") is not None:
            usage["cache_read_input_tokens"] = normalized_response.get("cache_read_input_tokens", 0)

        return {
            "id": normalized_response.get("id", "msg_xxx"),
            "type": "message",
            "role": "assistant",
            "content": content_blocks,
            "model": normalized_response.get("model", ""),
            "stop_reason": normalized_response.get("stop_reason", "end_turn"),
            "stop_sequence": normalized_response.get("stop_sequence"),
            "usage": usage,
        }

    def format_error(self, error: Exception) -> Dict[str, Any]:
        """Format error response."""
        return {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": str(error),
            },
        }
