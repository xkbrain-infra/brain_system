"""OpenAI /v1/responses protocol handler (Codex)."""
from typing import Any, Dict, List, Optional

from .base import (
    Message,
    NormalizedRequest,
    ProtocolHandler,
    Tool,
)


class ResponsesProtocolHandler(ProtocolHandler):
    """Handler for OpenAI /v1/responses API (Codex)."""

    @property
    def protocol_name(self) -> str:
        return "responses"

    def parse_request(self, body: Dict[str, Any]) -> NormalizedRequest:
        """Parse OpenAI responses request."""
        # Extract model
        model = body.get("model", "")

        # Parse input (can be messages or text)
        messages = []
        for item in body.get("input", []):
            if isinstance(item, dict):
                if item.get("type") == "message":
                    messages.append(Message(
                        role=item.get("role", "user"),
                        content=item.get("content", ""),
                    ))
                elif item.get("type") == "text":
                    messages.append(Message(
                        role="user",
                        content=item.get("text", ""),
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
                "stop": body.get("stop"),
                "response_format": body.get("response_format"),
                "tools": body.get("tools"),
            },
            original_request=body,
        )

    def format_response(self, normalized_response: Dict[str, Any]) -> Dict[str, Any]:
        """Format response to OpenAI responses format."""
        output_text = ""
        messages = normalized_response.get("messages", [])
        if messages:
            output_text = messages[0].content

        return {
            "id": normalized_response.get("id", "resp_xxx"),
            "object": "response",
            "created": normalized_response.get("created", 0),
            "model": normalized_response.get("model", ""),
            "output_text": output_text,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": normalized_response.get("input_tokens", 0),
                "output_tokens": normalized_response.get("output_tokens", 0),
                "total_tokens": normalized_response.get("input_tokens", 0) + normalized_response.get("output_tokens", 0),
            },
        }

    def format_error(self, error: Exception) -> Dict[str, Any]:
        """Format error response."""
        return {
            "error": {
                "message": str(error),
                "type": "server_error",
                "code": "internal_error",
            },
        }
