"""Data models for Telegram API Service."""

from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Attachment:
    """Attachment in a message."""
    type: str  # photo | document | video | audio
    file_id: str
    file_size: Optional[int] = None
    file_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StandardMessage:
    """Platform-agnostic standard message format."""
    platform: str  # "telegram"
    user_id: str
    username: str
    chat_id: str
    message_id: str
    content_type: str  # text | photo | document | video | audio
    content: str
    attachments: List[Attachment]
    timestamp: str  # ISO8601
    source: Optional[str] = None  # Bot name (e.g., "XKAgentBot")
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data['attachments'] = [a.to_dict() for a in self.attachments]
        return data


@dataclass
class SendMessageRequest:
    """Request to send message to Telegram."""
    chat_id: str
    content_type: str
    content: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)
