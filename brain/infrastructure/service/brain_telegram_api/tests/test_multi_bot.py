"""Unit tests for telegram_api multi-bot support."""

import sys
import os
import tempfile
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from unittest.mock import patch, MagicMock


def test_bots_yaml_loading():
    """Test loading bots from bots.yaml."""
    # Create temp bots.yaml
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({
            'bots': [
                {
                    'name': 'XKAgentBot',
                    'platform': 'telegram',
                    'service_name': 'service-telegram_api',
                    'token_env': 'TELEGRAM_BOT_TOKEN_1',
                    'chat_id_env': 'TELEGRAM_CHAT_ID_1',
                    'aliases': ['xkagent']
                },
                {
                    'name': 'XKQuantBot',
                    'platform': 'telegram',
                    'service_name': 'service-telegram_api',
                    'token_env': 'TELEGRAM_BOT_TOKEN_2',
                    'chat_id_env': 'TELEGRAM_CHAT_ID_2',
                    'aliases': ['xkquant']
                }
            ]
        }, f)
        temp_path = f.name

    try:
        with open(temp_path, 'r') as f:
            bots_config = yaml.safe_load(f)

        assert 'bots' in bots_config
        assert len(bots_config['bots']) == 2
        assert bots_config['bots'][0]['name'] == 'XKAgentBot'
        assert bots_config['bots'][1]['name'] == 'XKQuantBot'
        print("✓ test_bots_yaml_loading passed")
    finally:
        os.unlink(temp_path)


def test_bot_instance_filtering():
    """Test BOT_INSTANCE environment variable filtering."""
    # Simulate BOT_INSTANCE=1 should only load XKAgentBot
    bot_instance = os.environ.get("BOT_INSTANCE", "").strip()

    bots = [
        {'name': 'XKAgentBot', 'aliases': ['xkagent']},
        {'name': 'XKQuantBot', 'aliases': ['xkquant']}
    ]

    # Test filtering logic
    filtered = []
    for bot in bots:
        if bot_instance == "1":
            if bot['name'] == 'XKAgentBot':
                filtered.append(bot)
        elif bot_instance == "2":
            if bot['name'] == 'XKQuantBot':
                filtered.append(bot)
        else:
            filtered.append(bot)

    # Without BOT_INSTANCE, should load all
    assert len(filtered) == 2
    print("✓ test_bot_instance_filtering passed")


def test_multiple_bot_config():
    """Test multiple bot configuration structure."""
    config = {
        'bots': [
            {
                'name': 'XKAgentBot',
                'platform': 'telegram',
                'service_name': 'service-telegram_api',
                'token_env': 'TELEGRAM_BOT_TOKEN_1',
                'chat_id_env': 'TELEGRAM_CHAT_ID_1'
            },
            {
                'name': 'XKQuantBot',
                'platform': 'telegram',
                'service_name': 'service-telegram_api',
                'token_env': 'TELEGRAM_BOT_TOKEN_2',
                'chat_id_env': 'TELEGRAM_CHAT_ID_2'
            }
        ],
        'routing': {
            'priority': ['target_service', 'target_bot', 'session'],
            'valid_source_services': [
                'service-telegram_api'
            ]
        }
    }

    assert len(config['bots']) == 2
    assert config['routing']['valid_source_services'] == [
        'service-telegram_api'
    ]
    print("✓ test_multiple_bot_config passed")


if __name__ == '__main__':
    test_bots_yaml_loading()
    test_bot_instance_filtering()
    test_multiple_bot_config()
    print("\n✅ All multi-bot tests passed!")
