"""Telegram Bot API HTTP client."""

import httpx
import json
import logging
import sys
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger("telegram_client")


class TelegramClient:
    """HTTP client for Telegram Bot API."""

    def __init__(self, bot_token: str, timeout: int = 35):
        """Initialize Telegram client.

        Args:
            bot_token: Bot token from /xkagent_infra/brain/secrets/IM/telegram/bot_token.env
            timeout: HTTP request timeout in seconds
        """
        self.bot_token = bot_token.strip() if isinstance(bot_token, str) else bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

        # DEBUG: Force output to stderr to see actual token value
        sys.stderr.write(f"\n=== TELEGRAM_CLIENT DEBUG ===\n")
        sys.stderr.write(f"bot_token repr: {repr(bot_token)}\n")
        sys.stderr.write(f"bot_token type: {type(bot_token)}\n")
        sys.stderr.write(f"bot_token len: {len(bot_token) if bot_token else 'N/A'}\n")
        sys.stderr.write(f"bot_token.strip() repr: {repr(self.bot_token)}\n")
        sys.stderr.write(f"base_url repr: {repr(self.base_url)}\n")
        sys.stderr.write(f"base_url[60:80]: {repr(self.base_url[60:80] if len(self.base_url) > 60 else 'N/A')}\n")
        sys.stderr.write(f"=== END DEBUG ===\n\n")
        sys.stderr.flush()

    def get_updates(self, offset: int = 0, timeout: int = 30) -> List[Dict[str, Any]]:
        """Fetch updates using long polling.

        Args:
            offset: Update ID offset (to avoid duplicates)
            timeout: Long polling timeout in seconds

        Returns:
            List of updates from Telegram API

        Raises:
            Exception: On API error or network failure
        """
        url = f"{self.base_url}/getUpdates"
        payload = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message"]  # Only fetch message updates
        }

        try:
            # Debug: log the URL before request
            logger.debug(f"Request URL: {repr(url)}")
            logger.debug(f"Request params: {repr(payload)}")
            resp = self.client.get(url, params=payload, timeout=timeout + 5)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("getUpdates timeout (expected for long polling)")
            return []
        except httpx.RequestError as e:
            logger.error(f"Network error calling getUpdates: {e}")
            raise

        data = resp.json()

        if not data.get('ok'):
            error_msg = data.get('description', 'Unknown error')
            logger.error(f"Telegram API error: {error_msg}")
            raise Exception(f"Telegram API error: {error_msg}")

        return data.get('result', [])

    def send_message(self, chat_id: str, text: str) -> Dict[str, Any]:
        """Send text message.

        Args:
            chat_id: Telegram chat ID
            text: Message text

        Returns:
            API response result

        Raises:
            Exception: On API error
        """
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text
        }

        try:
            resp = self.client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Failed to send message: {e}")
            raise

        data = resp.json()

        if not data.get('ok'):
            error_msg = data.get('description', 'Unknown error')
            logger.error(f"Send message failed: {error_msg}")
            raise Exception(f"Send message failed: {error_msg}")

        return data.get('result', {})

    def send_photo(self, chat_id: str, photo_path: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Send photo message.

        Args:
            chat_id: Telegram chat ID
            photo_path: Local file path to photo
            caption: Optional photo caption

        Returns:
            API response result

        Raises:
            Exception: On API error or file error
        """
        url = f"{self.base_url}/sendPhoto"

        try:
            with open(photo_path, 'rb') as f:
                files = {"photo": f}
                data = {
                    "chat_id": chat_id,
                }
                if caption:
                    data["caption"] = caption

                resp = self.client.post(url, files=files, data=data)
                resp.raise_for_status()
        except FileNotFoundError:
            logger.error(f"Photo file not found: {photo_path}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Failed to send photo: {e}")
            raise

        data = resp.json()

        if not data.get('ok'):
            error_msg = data.get('description', 'Unknown error')
            logger.error(f"Send photo failed: {error_msg}")
            raise Exception(f"Send photo failed: {error_msg}")

        return data.get('result', {})

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
