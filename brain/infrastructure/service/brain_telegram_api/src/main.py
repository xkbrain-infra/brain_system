"""Telegram API Service - Main entry point (BS-028-T3 patched).

Unified service that manages multiple Telegram bots via polling.
Patched for BS-028-T3: Hot reload with SIGHUP support.
"""

import asyncio
import json
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path
from typing import Dict, Any, List

import yaml

from telegram_client import TelegramClient
from offset_manager import OffsetManager
from polling_engine import PollingEngine
from models import StandardMessage
from hot_reload import BotsReloader

# BS-028-T3: Import reload manager
from reload_manager import ReloadManager, validate_bots_config, build_bots_runtime
from config_store import get_config_store


# Setup logging
def setup_logging():
    """Configure structured JSON logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    # JSON format
    formatter = logging.Formatter(
        '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logging()

# IPC polling cadence:
# - busy: shortly after traffic, keep responsiveness
# - idle: prolonged silence, reduce CPU usage
IPC_POLL_BUSY_SLEEP_SECONDS = 0.6
IPC_POLL_IDLE_SLEEP_SECONDS = 5.0


def load_config(config_path: str) -> Dict[str, Any]:
    """Load YAML configuration.

    Args:
        config_path: Path to telegram.yaml

    Returns:
        Configuration dictionary
    """
    if not os.path.exists(config_path):
        logger.warning(f"Config not found: {config_path}, using defaults")
        return {}

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}

    logger.info(f"Loaded config from {config_path}")
    return config


def load_bot_token(token_file: str, token_env: str = None) -> str:
    """Load Telegram bot token from environment variable or file.

    Args:
        token_file: Path to bot_token.env file
        token_env: Environment variable name for token (e.g., TELEGRAM_BOT_TOKEN_N)

    Returns:
        Bot token string

    Raises:
        FileNotFoundError: If token file not found
        ValueError: If token not found
    """
    # Priority 1: Environment variable
    if token_env:
        token = os.environ.get(token_env)
        if token:
            logger.info(f"Loaded bot token from environment: {token_env}")
            return token.strip()

    # Priority 2: File-based token
    if not os.path.exists(token_file):
        raise FileNotFoundError(f"Token file not found: {token_file}")

    with open(token_file, 'r') as f:
        content = f.read()

    # If token_env specified, look for it in file
    if token_env:
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith(token_env + '='):
                token = line.split('=', 1)[1].strip()
                if token:
                    logger.info(f"Loaded bot token from file: {token_env}")
                    return token
        raise ValueError(f"Token {token_env} not found in {token_file}")

    # Fallback: first token in file
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('TELEGRAM_BOT_TOKEN') and '=' in line:
            token = line.split('=', 1)[1].strip()
            if token:
                logger.info("Loaded bot token from file (first available)")
                return token

    raise ValueError(f"No token found in {token_file}")


class BotInstance:
    """Single bot instance with its own polling engine."""

    def __init__(self, name: str, token: str, chat_id: str = None):
        self.name = name
        self.token = token
        self.chat_id = chat_id
        self.client = TelegramClient(token)
        self.polling_engine = None
        self.offset_manager = None

    async def initialize(self, offset_db_path: str, polling_config: dict, message_handler):
        """Initialize polling engine for this bot."""
        # Each bot has its own offset manager
        db_path = offset_db_path.replace('.db', f'_{self.name}.db')
        self.offset_manager = OffsetManager(db_path)

        self.polling_engine = PollingEngine(
            self.client,
            self.offset_manager,
            message_handler,
            polling_timeout=polling_config.get('timeout_seconds', 30),
            max_retries=polling_config.get('max_retries', 3),
            bot_name=self.name
        )

        logger.info(f"Bot '{self.name}' initialized with token {self.token[:10]}...")

    async def start(self):
        """Start polling for this bot."""
        if self.polling_engine:
            await self.polling_engine.run()

    async def stop(self):
        """Stop polling for this bot."""
        if self.polling_engine:
            await self.polling_engine.stop()
            logger.info(f"Bot '{self.name}' stopped")


class TelegramAPIService:
    """Unified Telegram API Service managing multiple bots."""

    def __init__(self, config_path: str):
        """Initialize service.

        Args:
            config_path: Path to telegram.yaml
        """
        self.config = load_config(config_path)
        self.service_config = self.config.get('service', {})
        # Allow SERVICE_NAME env var to override config (for multi-instance deployments)
        self.service_name = os.environ.get('SERVICE_NAME', self.service_config.get('name', 'service-telegram_api'))

        self.polling_config = self.config.get('telegram', {}).get('polling', {})
        self.ipc_config = self.config.get('ipc', {})
        self.offset_config = self.config.get('offset_manager', {})

        # BS-028-T3: Hot reload configuration
        self.hot_reload_config = self.service_config.get('enable_hot_reload', False)

        # Load bot configurations
        self.bots: List[BotInstance] = []
        self._load_bots()
        self._recent_sources: Dict[str, Dict[str, Any]] = {}

        self.daemon_client = None
        self._shutting_down = False

        # Hot reload configuration - BS-028-T3
        self._bots_reloader: BotsReloader = None
        self._reload_manager: ReloadManager = None  # BS-028-T3: SIGHUP-based reload manager

        # Signal handling
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigint)
        # BS-028-T3: SIGHUP handler is registered by ReloadManager.start()

        logger.info(f"Service initialized: {self.service_name} with {len(self.bots)} bots, hot_reload={self.hot_reload_config}")

    async def _on_bots_reload(self, added_bots, removed_bot_names, changed_bots):
        """Handle bots configuration reload.

        Args:
            added_bots: List of new BotConfig objects to add
            removed_bot_names: List of bot names to remove
            changed_bots: List of BotConfig objects with updated configuration
        """
        logger.info(f"Hot reload: {len(added_bots)} added, {len(removed_bot_names)} removed, {len(changed_bots)} changed")

        # Remove bots that are no longer in config
        for bot_name in removed_bot_names:
            for bot in self.bots[:]:  # Iterate over copy
                if bot.name == bot_name:
                    logger.info(f"Stopping removed bot: {bot_name}")
                    await bot.stop()
                    bot.client.close()
                    self.bots.remove(bot)
                    break

        # Add new bots
        offset_db_path = self.offset_config.get('db_path', '/xkagent_infra/brain/infrastructure/data/telegram_api/offset.db')
        for bot_cfg in added_bots:
            logger.info(f"Starting new bot: {bot_cfg.name}")
            new_bot = BotInstance(bot_cfg.name, bot_cfg.token, bot_cfg.chat_id)
            await new_bot.initialize(offset_db_path, self.polling_config, self._handle_message)
            self.bots.append(new_bot)
            asyncio.create_task(new_bot.start())

        # Update changed bots (restart with new config)
        for bot_cfg in changed_bots:
            for bot in self.bots:
                if bot.name == bot_cfg.name:
                    logger.info(f"Restarting changed bot: {bot_cfg.name}")
                    await bot.stop()
                    bot.token = bot_cfg.token
                    bot.chat_id = bot_cfg.chat_id
                    bot.client = TelegramClient(bot_cfg.token)
                    await bot.initialize(offset_db_path, self.polling_config, self._handle_message)
                    asyncio.create_task(bot.start())
                    break

        logger.info(f"Hot reload complete. Current bots: {[b.name for b in self.bots]}")

    def start_hot_reload(self):
        """Start hot reload with SIGHUP support (BS-028-T3)."""
        if not self.hot_reload_config:
            logger.info("Hot reload disabled (enable_hot_reload=false)")
            # Still start file watcher as fallback
            self._start_file_watcher_fallback()
            return

        bots_yaml_path = "/xkagent_infra/brain/infrastructure/config/third_api/telegram/telegram.yaml"
        if not os.path.exists(bots_yaml_path):
            logger.warning(f"bots.yaml not found: {bots_yaml_path}")
            return

        # BS-028-T3: Create reload manager with SIGHUP support
        try:
            self._reload_manager = ReloadManager(
                config_path=bots_yaml_path,
                validate_fn=validate_bots_config,
                build_runtime_fn=build_bots_runtime,
                on_reload_callback=self._on_bots_reload
            )

            # Initialize config store
            config_store = get_config_store()

            # Load initial config
            with open(bots_yaml_path, 'r') as f:
                initial_config = yaml.safe_load(f) or {}

            runtime = build_bots_runtime(initial_config)
            config_store.initialize(initial_config, runtime)

            # Start reload manager (registers SIGHUP handler)
            self._reload_manager.start()
            logger.info("Hot reload enabled with SIGHUP support")
        except Exception as e:
            logger.error(f"Failed to start reload manager: {e}, falling back to file watcher")
            self._start_file_watcher_fallback()

    def _start_file_watcher_fallback(self):
        """Start file watcher as fallback (original implementation)."""
        bots_yaml_path = "/xkagent_infra/brain/infrastructure/config/third_api/telegram/telegram.yaml"
        if not os.path.exists(bots_yaml_path):
            logger.warning(f" bots.yaml not found: {bots_yaml_path}")
            return

        self._bots_reloader = BotsReloader(bots_yaml_path, self._on_bots_reload)
        self._bots_reloader.start_watching()
        logger.info("File watcher fallback enabled for bots.yaml")

    def _load_bots(self):
        """Load bot configurations from bots.yaml and telegram.yaml."""
        # BS-022-T1.3: Load from bots.yaml first (canonical source)
        bots_yaml_path = "/xkagent_infra/brain/infrastructure/config/third_api/telegram/telegram.yaml"

        if os.path.exists(bots_yaml_path):
            try:
                with open(bots_yaml_path, 'r') as f:
                    bots_registry = yaml.safe_load(f)
                    bots_from_yaml = bots_registry.get('bots', [])

                if bots_from_yaml:
                    logger.info(f"Loading {len(bots_from_yaml)} bots from bots.yaml")

                    # Filter by BOT_INSTANCE if specified
                    bot_instance = os.environ.get("BOT_INSTANCE", "").strip()

                    for idx, bot_cfg in enumerate(bots_from_yaml, start=1):
                        name = bot_cfg.get('name')
                        token_env = bot_cfg.get('token_env')
                        chat_id_env = bot_cfg.get('chat_id_env')
                        service_name = bot_cfg.get('service_name')

                        # BS-022-T2.1: If BOT_INSTANCE specified, only load the indexed bot.
                        if bot_instance and bot_instance != str(idx):
                            continue

                        # Try env var first, then fall back to token files
                        token = os.environ.get(token_env) if token_env else None
                        if not token and token_env:
                            token_files = os.environ.get(
                                'TELEGRAM_BOT_TOKEN_FILE', ''
                            ).split(',')
                            for tf in token_files:
                                tf = tf.strip()
                                if not tf:
                                    continue
                                try:
                                    token = load_bot_token(tf, token_env)
                                    if token:
                                        break
                                except Exception:
                                    pass
                        if token:
                            chat_id = os.environ.get(chat_id_env) if chat_id_env else None
                            self.bots.append(BotInstance(name, token.strip(), chat_id))
                            logger.info(f"Loaded bot '{name}' from config (service: {service_name})")
                        else:
                            logger.warning(f"Skipping bot '{name}': no token for {token_env}")

                    if self.bots:
                        logger.info(f"Loaded {len(self.bots)} bots from bots.yaml")
                        return
            except Exception as e:
                logger.warning(f"Failed to load bots.yaml: {e}, falling back to telegram.yaml")

        # Fallback: load from telegram.yaml config
        token_file = self.config.get('telegram', {}).get('bot_token_file')
        if not token_file:
            token_file = os.environ.get('TELEGRAM_BOT_TOKEN_FILE', '/xkagent_infra/brain/secrets/IM/telegram/bot_token.env')

        bots_config = self.config.get('bots', [])
        bot_instance = os.environ.get("BOT_INSTANCE", "").strip()
        target_bot_name = f"bot{bot_instance}" if bot_instance else ""

        if not bots_config:
            if bot_instance:
                token_env = f"TELEGRAM_BOT_TOKEN_{bot_instance}"
                chat_id_env = f"TELEGRAM_CHAT_ID_{bot_instance}"
                token = os.environ.get(token_env)
                if token:
                    chat_id = os.environ.get(chat_id_env)
                    self.bots.append(BotInstance(target_bot_name, token.strip(), chat_id))
                    logger.info(f"Loaded {target_bot_name} from environment (BOT_INSTANCE={bot_instance})")
            else:
                for i in range(1, 10):
                    token_env = f"TELEGRAM_BOT_TOKEN_{i}"
                    chat_id_env = f"TELEGRAM_CHAT_ID_{i}"
                    token = os.environ.get(token_env)
                    if token:
                        chat_id = os.environ.get(chat_id_env)
                        self.bots.append(BotInstance(f"bot{i}", token.strip(), chat_id))
                        logger.info(f"Loaded bot{i} from environment")
                    else:
                        break

            if not self.bots:
                try:
                    token = load_bot_token(token_file)
                    default_name = target_bot_name if target_bot_name else "default"
                    self.bots.append(BotInstance(default_name, token))
                    logger.info(f"Loaded {default_name} from file")
                except Exception as e:
                    logger.error(f"Failed to load any bot: {e}")
        else:
            selected_bots = bots_config
            if target_bot_name:
                selected_bots = [
                    b for b in bots_config
                    if b.get('name') == target_bot_name
                    or b.get('token_env') == f"TELEGRAM_BOT_TOKEN_{bot_instance}"
                ]
                if not selected_bots:
                    logger.warning(
                        "BOT_INSTANCE=%s set but no matching bot config found; fallback to all bots",
                        bot_instance,
                    )
                    selected_bots = bots_config

            for bot_cfg in selected_bots:
                token_env = bot_cfg.get('token_env')
                chat_id_env = bot_cfg.get('chat_id_env')
                name = bot_cfg.get('name', 'unknown')

                token = os.environ.get(token_env) if token_env else None
                if not token and token_file:
                    try:
                        token = load_bot_token(token_file, token_env)
                    except:
                        pass

                if token:
                    chat_id = os.environ.get(chat_id_env) if chat_id_env else None
                    self.bots.append(BotInstance(name, token.strip(), chat_id))
                    logger.info(f"Loaded bot '{name}' from config")
                else:
                    logger.warning(f"Skipping bot '{name}': no token found")

    async def _init_ipc_client(self):
        """Initialize IPC daemon client."""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "daemon_client",
                "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            DaemonClient = module.DaemonClient

            socket_path = self.ipc_config.get('socket_path', '/tmp/brain_ipc.sock')
            self.daemon_client = DaemonClient(socket_path)

            await asyncio.to_thread(
                self.daemon_client._send_request,
                "service_register",
                {"service_name": self.service_name, "metadata": {"type": "im_api", "platform": "telegram", "bots": [b.name for b in self.bots]}}
            )
            logger.info(f"Registered to IPC: {self.service_name}")
        except Exception as e:
            logger.error(f"Failed to initialize IPC client: {e}")
            self.daemon_client = None

    async def _handle_message(self, msg: StandardMessage):
        """Handle received message.

        Args:
            msg: StandardMessage object
        """
        try:
            if not self.daemon_client:
                logger.warning("IPC client not available, message not sent")
                return

            target = self.ipc_config.get('target_gateway', 'service-brain_gateway')
            self._remember_recent_source(msg)

            payload = msg.to_dict()
            payload['source_bot'] = msg.source

            await asyncio.to_thread(
                self.daemon_client.send,
                from_agent=self.service_name,
                to_agent=target,
                payload=payload,
                message_type="request"
            )
            logger.info(f"Sent message to {target}: {msg.message_id}")

        except Exception as e:
            logger.error(f"Error sending message via IPC: {e}")

    def _select_bot(self, target_bot: str = None):
        """Select target bot by name, fallback to first bot."""
        if target_bot:
            for bot in self.bots:
                if bot.name == target_bot:
                    return bot
        return self.bots[0] if self.bots else None

    def _remember_recent_source(self, msg: StandardMessage):
        """Cache the latest inbound Telegram source for fallback replies."""
        context = {
            "platform": msg.platform,
            "chat_id": str(msg.chat_id or ""),
            "user_id": str(msg.user_id or ""),
            "username": msg.username or "",
            "message_id": str(msg.message_id or ""),
            "source_bot": msg.source or "",
            "target_bot": msg.source or "",
        }
        self._recent_sources["__latest__"] = context
        if context["source_bot"]:
            self._recent_sources[f"bot:{context['source_bot']}"] = context

    def _normalize_inbound_payload(self, msg: dict) -> dict:
        """Normalize IPC payloads, including JSON-string content from MCP clients."""
        payload = dict(msg.get('payload', {}) or {})
        content = payload.get('content')
        if isinstance(content, str):
            stripped = content.strip()
            parsed = None
            if stripped.startswith('{'):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = None
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if key == 'content' or key not in payload or payload.get(key) in ("", None):
                        payload[key] = value
        if not payload.get('target_bot') and payload.get('source_bot'):
            payload['target_bot'] = payload['source_bot']
        if not payload.get('platform') and (payload.get('chat_id') or payload.get('user_id')):
            payload['platform'] = 'telegram'
        return payload

    def _resolve_recent_source(self, payload: dict) -> Dict[str, Any]:
        """Resolve cached source context for recent-source fallback."""
        target_bot = payload.get('target_bot') or payload.get('source_bot')
        if target_bot:
            context = self._recent_sources.get(f"bot:{target_bot}")
            if context:
                return context
        return self._recent_sources.get("__latest__", {})

    async def _send_via_bot(self, payload: dict, log_prefix: str):
        """Send payload content to Telegram using selected bot."""
        content = payload.get('content')
        chat_id = payload.get('chat_id') or payload.get('user_id')
        target_bot = payload.get('target_bot') or payload.get('source_bot')
        if (not chat_id or not target_bot) and payload.get('recent_source'):
            recent_source = self._resolve_recent_source(payload)
            chat_id = chat_id or recent_source.get('chat_id') or recent_source.get('user_id')
            target_bot = target_bot or recent_source.get('target_bot') or recent_source.get('source_bot')
            payload['platform'] = payload.get('platform') or recent_source.get('platform', 'telegram')
        if not content:
            logger.warning("Missing outbound content for payload type=%s", payload.get('type', ''))
            return False
        bot = self._select_bot(target_bot)
        if not chat_id:
            logger.warning(
                "Missing chat_id for outbound payload type=%s recent_source=%s",
                payload.get('type', ''),
                bool(payload.get('recent_source')),
            )
            return False
        if not bot:
            logger.warning("No Telegram bot available for target_bot=%s", target_bot or "")
            return False
        await asyncio.to_thread(bot.client.send_message, str(chat_id), content)
        logger.info(f"{log_prefix} {chat_id} via {bot.name}")
        return True

    async def _process_inbound_message(self, msg: dict) -> bool:
        """Process one IPC message and report whether it is safe to ACK."""
        from_agent = msg.get('from', '')
        payload = self._normalize_inbound_payload(msg)
        msg_type = payload.get('type', '')

        if from_agent in ("service-brain_gateway", "service-agent_gateway"):
            return await self._send_via_bot(payload, "Sent reply to")
        if msg_type in ('send_message_request', 'FRONTDESK_OUTBOUND'):
            return await self._send_via_bot(payload, "Sent message to")

        logger.info(
            "Ignoring unsupported IPC message: from=%s type=%s msg_id=%s",
            from_agent,
            msg_type,
            msg.get('msg_id'),
        )
        return True

    async def _receive_inbound_messages(self):
        """Single IPC receive loop."""
        if not self.daemon_client:
            return

        was_busy = True
        try:
            while True:
                try:
                    result = await asyncio.to_thread(
                        self.daemon_client.recv,
                        agent_name=self.service_name,
                        ack_mode="manual",
                        max_items=20
                    )

                    messages = result.get('messages', [])
                    if not messages:
                        sleep_s = IPC_POLL_BUSY_SLEEP_SECONDS if was_busy else IPC_POLL_IDLE_SLEEP_SECONDS
                        await asyncio.sleep(sleep_s)
                        was_busy = False
                        continue

                    was_busy = True
                    msg_ids = []
                    for msg in messages:
                        try:
                            success = await self._process_inbound_message(msg)
                        except Exception as e:
                            success = False
                            logger.error(f"Error processing inbound message: {e}")
                        if success and msg.get('msg_id'):
                            msg_ids.append(msg['msg_id'])

                    if msg_ids:
                        await asyncio.to_thread(
                            self.daemon_client.ack,
                            agent_name=self.service_name,
                            msg_ids=msg_ids
                        )

                except Exception as e:
                    logger.debug(f"Error receiving inbound messages: {e}")
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Fatal error in inbound listener: {e}")

    def _handle_sigterm(self, signum, frame):
        """Handle SIGTERM signal."""
        logger.info("Received SIGTERM, shutting down gracefully")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.shutdown())
        except RuntimeError:
            pass

    def _handle_sigint(self, signum, frame):
        """Handle SIGINT signal."""
        logger.info("Received SIGINT, shutting down gracefully")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.shutdown())
        except RuntimeError:
            pass

    async def shutdown(self):
        """Shutdown service gracefully."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down service")

        # BS-028-T3: Stop reload manager
        if self._reload_manager:
            self._reload_manager.stop()

        # Stop hot reload watcher (fallback)
        if self._bots_reloader:
            self._bots_reloader.stop_watching()

        # Stop all bot polling engines
        for bot in self.bots:
            await bot.stop()
            bot.client.close()

        if self.daemon_client:
            try:
                self.daemon_client.close()
            except:
                pass

    async def run(self):
        """Run service."""
        try:
            if not self.bots:
                logger.error("No bots configured, exiting")
                return

            # Start hot reload (BS-028-T3: with SIGHUP support)
            self.start_hot_reload()

            # Initialize IPC
            await self._init_ipc_client()

            # Initialize all bots
            offset_db_path = self.offset_config.get('db_path', '/xkagent_infra/brain/infrastructure/data/telegram_api/offset.db')
            for bot in self.bots:
                await bot.initialize(offset_db_path, self.polling_config, self._handle_message)

            # Start all bot polling tasks
            polling_tasks = [bot.start() for bot in self.bots]

            # Run all polling engines, reply listener, and send request listener concurrently
            await asyncio.gather(
                *polling_tasks,
                self._receive_inbound_messages()
            )

        except Exception as e:
            logger.error(f"Service error: {e}")
        finally:
            await self.shutdown()


def main():
    """Main entry point."""
    config_path = os.environ.get(
        'TELEGRAM_CONFIG',
        '/xkagent_infra/brain/infrastructure/config/third_api/telegram/telegram.yaml'
    )

    service = TelegramAPIService(config_path)

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Service interrupted")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
