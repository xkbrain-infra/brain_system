"""Long polling engine for Telegram messages."""

import asyncio
import logging
import time
from typing import Callable, Optional
from telegram_client import TelegramClient
from offset_manager import OffsetManager
from message_converter import MessageConverter
from models import StandardMessage

logger = logging.getLogger("polling_engine")


class PollingEngine:
    """Long polling engine for Telegram Bot API."""

    def __init__(
        self,
        telegram_client: TelegramClient,
        offset_manager: OffsetManager,
        message_handler: Callable,
        polling_timeout: int = 30,
        max_retries: int = 3,
        bot_name: str = None
    ):
        """Initialize polling engine.

        Args:
            telegram_client: TelegramClient instance
            offset_manager: OffsetManager instance
            message_handler: Async function to handle StandardMessage
            polling_timeout: getUpdates timeout in seconds
            max_retries: Max retry attempts on error
            bot_name: Name of the bot this engine handles
        """
        self.client = telegram_client
        self.offset_manager = offset_manager
        self.message_handler = message_handler
        self.polling_timeout = polling_timeout
        self.max_retries = max_retries
        self.bot_name = bot_name
        self.running = False

    async def run(self):
        """Main polling loop.

        Continuously fetches updates from Telegram and processes them.
        """
        self.running = True
        retry_count = 0
        retry_delay = 1

        logger.info("Starting polling engine")

        try:
            while self.running:
                try:
                    offset = self.offset_manager.get_offset()
                    logger.debug(f"Polling with offset={offset}")

                    # Fetch updates (blocking call in thread)
                    updates = await asyncio.to_thread(
                        self.client.get_updates,
                        offset=offset,
                        timeout=self.polling_timeout
                    )

                    if updates:
                        logger.info(f"Received {len(updates)} updates")
                        retry_count = 0  # Reset retry counter
                        retry_delay = 1

                        for update in updates:
                            try:
                                # Convert to standard format (include bot_name)
                                msg = await asyncio.to_thread(
                                    MessageConverter.convert,
                                    update,
                                    self.bot_name
                                )
                                logger.debug(f"Converted message: {msg.message_id}")

                                # Handle message
                                await self.message_handler(msg)

                                # Update offset
                                self.offset_manager.update(update['update_id'])
                                logger.debug(f"Updated offset to {update['update_id'] + 1}")

                            except Exception as e:
                                logger.error(f"Error handling update {update.get('update_id')}: {e}")
                                # Continue to next update
                    else:
                        logger.debug("No updates received (timeout)")

                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    retry_count += 1

                    if retry_count > self.max_retries:
                        logger.error(f"Max retries ({self.max_retries}) exceeded, stopping")
                        break

                    # Exponential backoff
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                    logger.info(f"Retrying in {retry_delay} seconds (attempt {retry_count})")

        except Exception as e:
            logger.error(f"Fatal error in polling loop: {e}")
        finally:
            self.running = False
            logger.info("Polling engine stopped")

    async def stop(self):
        """Stop the polling engine."""
        logger.info("Stopping polling engine")
        self.running = False
        # Give it a moment to exit gracefully
        await asyncio.sleep(0.5)

    def get_stats(self) -> dict:
        """Get polling engine statistics.

        Returns:
            Dictionary with stats
        """
        return {
            "running": self.running,
            "offset": self.offset_manager.get_stats()
        }
