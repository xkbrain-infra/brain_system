"""OpenAI /v1/chat/completions protocol handler."""
from typing import Any, Dict, List, Optional, Union

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


class ChatCompletionsProtocolHandler(ProtocolHandler):
    """Handler for OpenAI /v1/chat/completions API."""

    @property
    def protocol_name(self) -> str:
        return "chat_completions"

    def parse_request(self, body: Dict[str, Any]) -> NormalizedRequest:
        """Parse OpenAI chat completions request."""
        # Extract model
        model = body.get("model", "")

        # Parse messages
        messages = []
        for msg in body.get("messages", []):
            messages.append(Message(
                role=msg.get("role", "user"),
                content=_normalize_content(msg.get("content", "")),
                name=msg.get("name"),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
            ))

        # Parse tools
        tools = None
        if "tools" in body:
            tools = [
                Tool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("parameters", t.get("input_schema", {})),
                )
                for t in body["tools"]
            ]

        return NormalizedRequest(
            model=model,
            messages=messages,
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            tools=tools,
            stream=body.get("stream", False),
            metadata={
                "top_p": body.get("top_p"),
                "n": body.get("n"),
                "stop": body.get("stop"),
                "presence_penalty": body.get("presence_penalty"),
                "frequency_penalty": body.get("frequency_penalty"),
                "logit_bias": body.get("logit_bias"),
                "user": body.get("user"),
            },
            original_request=body,
        )

    def format_response(self, normalized_response: Dict[str, Any]) -> Dict[str, Any]:
        """Format response to OpenAI chat completions format."""
        # Copilot returns choices directly, not wrapped in messages
        choices = normalized_response.get("choices", [])

        # If choices is empty, try to get content from messages (for other providers)
        if not choices and normalized_response.get("messages"):
            for i, msg in enumerate(normalized_response.get("messages", [])):
                choices.append({
                    "index": i,
                    "message": {
                        "role": msg.role if hasattr(msg, 'role') else "assistant",
                        "content": msg.content if hasattr(msg, 'content') else str(msg),
                    },
                    "finish_reason": normalized_response.get("finish_reason", "stop"),
                })

        return {
            "id": normalized_response.get("id", "chatcmpl-xxx"),
            "object": "chat.completion",
            "created": normalized_response.get("created", 0),
            "model": normalized_response.get("model", ""),
            "choices": choices,
            "usage": {
                "prompt_tokens": normalized_response.get("input_tokens", 0),
                "completion_tokens": normalized_response.get("output_tokens", 0),
                "total_tokens": normalized_response.get("input_tokens", 0) + normalized_response.get("output_tokens", 0),
            },
        }

    def format_error(self, error: Exception) -> Dict[str, Any]:
        """Format error response."""
        return {
            "error": {
                "message": str(error),
                "type": "server_error",
                "param": None,
                "code": "internal_error",
            },
        }
