"""Convert Telegram messages to standard format."""

import logging
from datetime import datetime
from typing import Dict, Any, List
from models import StandardMessage, Attachment

logger = logging.getLogger("message_converter")


class MessageConverter:
    """Converts Telegram API messages to standard format."""

    @staticmethod
    def convert(update: Dict[str, Any], bot_name: str = None) -> StandardMessage:
        """Convert Telegram update to StandardMessage.

        Args:
            update: Telegram API update object
            bot_name: Name of the bot that received the message

        Returns:
            StandardMessage object

        Raises:
            ValueError: If message format is invalid
        """
        msg = update.get('message', {})
        if not msg:
            raise ValueError("Update has no message")

        user = msg.get('from', {})
        chat = msg.get('chat', {})

        # Extract content and type
        content_type, content = MessageConverter._extract_content(msg)

        # Extract attachments
        attachments = MessageConverter._extract_attachments(msg)

        # Build StandardMessage
        standard_msg = StandardMessage(
            platform="telegram",
            user_id=str(user.get('id', '')),
            username=user.get('username', 'unknown'),
            chat_id=str(chat.get('id', '')),
            message_id=str(msg.get('message_id', '')),
            content_type=content_type,
            content=content,
            attachments=attachments,
            timestamp=MessageConverter._get_timestamp(msg),
            source=bot_name,
            metadata={
                "first_name": user.get('first_name', ''),
                "chat_type": chat.get('type', ''),
            }
        )

        logger.debug(f"Converted message: {standard_msg.message_id} from {standard_msg.user_id}")
        return standard_msg

    @staticmethod
    def _extract_content(msg: Dict[str, Any]) -> tuple:
        """Extract message content and type.

        Returns:
            (content_type, content) tuple
        """
        if msg.get('text'):
            return "text", msg.get('text', '')

        if msg.get('photo'):
            # Return largest photo file_id
            photos = msg.get('photo', [])
            if photos:
                return "photo", photos[-1].get('file_id', '')

        if msg.get('document'):
            doc = msg.get('document', {})
            return "document", doc.get('file_id', '')

        if msg.get('video'):
            video = msg.get('video', {})
            return "video", video.get('file_id', '')

        if msg.get('audio'):
            audio = msg.get('audio', {})
            return "audio", audio.get('file_id', '')

        logger.warning(f"Unknown message type in update")
        return "text", "[Unsupported message type]"

    @staticmethod
    def _extract_attachments(msg: Dict[str, Any]) -> List[Attachment]:
        """Extract attachments from message.

        Returns:
            List of Attachment objects
        """
        attachments = []

        # Photos
        if msg.get('photo'):
            photos = msg.get('photo', [])
            if photos:
                largest = photos[-1]
                attachments.append(Attachment(
                    type="photo",
                    file_id=largest.get('file_id', ''),
                    file_size=largest.get('file_size')
                ))

        # Document
        if msg.get('document'):
            doc = msg.get('document', {})
            attachments.append(Attachment(
                type="document",
                file_id=doc.get('file_id', ''),
                file_size=doc.get('file_size')
            ))

        # Video
        if msg.get('video'):
            video = msg.get('video', {})
            attachments.append(Attachment(
                type="video",
                file_id=video.get('file_id', ''),
                file_size=video.get('file_size')
            ))

        # Audio
        if msg.get('audio'):
            audio = msg.get('audio', {})
            attachments.append(Attachment(
                type="audio",
                file_id=audio.get('file_id', ''),
                file_size=audio.get('file_size')
            ))

        return attachments

    @staticmethod
    def _get_timestamp(msg: Dict[str, Any]) -> str:
        """Get ISO8601 timestamp from Telegram message.

        Returns:
            ISO8601 timestamp string
        """
        timestamp = msg.get('date', 0)
        if timestamp:
            dt = datetime.utcfromtimestamp(timestamp)
            return dt.isoformat() + 'Z'
        return datetime.utcnow().isoformat() + 'Z'
