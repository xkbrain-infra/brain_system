# Telegram API Service

Telegram Bot API integration service for Brain system. Handles message polling and routing.

## Architecture

- **PollingEngine**: Long polls Telegram API for messages
- **MessageConverter**: Converts Telegram messages to standard format
- **OffsetManager**: Manages update offsets to prevent duplicates
- **TelegramClient**: HTTP client for Telegram Bot API

## Setup

### Prerequisites

- Python 3.8+
- Telegram bot token in `/brain/secrets/IM/telegram/bot_token.env`
- Brain IPC daemon running

### Installation

```bash
cd /brain/infrastructure/service/telegram_api
pip install -r requirements.txt
```

### Configuration

Edit `config/telegram.yaml`:
- `telegram.bot_token_file`: Path to bot token file
- `telegram.polling.timeout_seconds`: Long polling timeout (default: 30)
- `ipc.socket_path`: IPC daemon socket path

## Running

```bash
# Via supervisor
supervisorctl start service_telegram_api

# Directly
python src/main.py
```

## Testing

```bash
cd tests
python test_converter.py
```

## Logging

- Format: JSON
- Level: INFO (configurable)
- Output: stdout

## Message Flow

1. Long poll Telegram API (getUpdates)
2. Convert message to standard format
3. Send to agent_gateway via IPC
4. Receive reply from agent_gateway
5. Send reply back to Telegram (sendMessage)
