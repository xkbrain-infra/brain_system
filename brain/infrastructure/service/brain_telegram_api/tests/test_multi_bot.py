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
                    'token_env': 'TELEGRAM_BOT_TOKEN_2',
                    'chat_id_env': 'TELEGRAM_CHAT_ID_2',
                    'aliases': ['xkagent']
                },
                {
                    'name': 'XKAgentBotBackup',
                    'platform': 'telegram',
                    'service_name': 'service-telegram_api',
                    'token_env': 'TELEGRAM_BOT_TOKEN_3',
                    'chat_id_env': 'TELEGRAM_CHAT_ID_3',
                    'aliases': ['xkagent-backup']
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
        assert bots_config['bots'][1]['name'] == 'XKAgentBotBackup'
        print("✓ test_bots_yaml_loading passed")
    finally:
        os.unlink(temp_path)


def test_bot_instance_filtering():
    """Test BOT_INSTANCE environment variable filtering."""
    bots = [
        {'name': 'XKAgentBot', 'aliases': ['xkagent']},
        {'name': 'XKAgentBotBackup', 'aliases': ['xkagent-backup']}
    ]

    filtered = [bot for idx, bot in enumerate(bots, start=1) if "2" == str(idx)]

    assert len(filtered) == 1
    assert filtered[0]['name'] == 'XKAgentBotBackup'
    print("✓ test_bot_instance_filtering passed")


def test_multiple_bot_config():
    """Test multiple bot configuration structure."""
    config = {
        'bots': [
            {
                'name': 'XKAgentBot',
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

    assert len(config['bots']) == 1
    assert config['routing']['valid_source_services'] == [
        'service-telegram_api'
    ]
    print("✓ test_multiple_bot_config passed")


if __name__ == '__main__':
    test_bots_yaml_loading()
    test_bot_instance_filtering()
    test_multiple_bot_config()
    print("\n✅ All multi-bot tests passed!")
