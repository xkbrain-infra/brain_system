"""Unit tests for hot reload functionality."""

import asyncio
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add src to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hot_reload import BotsReloader, BotConfig


class TestBotConfig:
    """Test BotConfig class."""

    def test_bot_config_creation(self):
        """Test creating a BotConfig object."""
        bot = BotConfig(
            name="TestBot",
            token="test_token",
            chat_id="123456",
            service_name="test_service"
        )
        assert bot.name == "TestBot"
        assert bot.token == "test_token"
        assert bot.chat_id == "123456"
        assert bot.service_name == "test_service"

    def test_bot_config_equality(self):
        """Test BotConfig equality."""
        bot1 = BotConfig(name="TestBot", token="token123", chat_id="123")
        bot2 = BotConfig(name="TestBot", token="token123", chat_id="123")
        bot3 = BotConfig(name="TestBot", token="different", chat_id="123")

        assert bot1 == bot2
        assert bot1 != bot3

    def test_bot_config_to_dict(self):
        """Test BotConfig to_dict method."""
        bot = BotConfig(name="TestBot", token="token123", chat_id="123")
        d = bot.to_dict()

        assert d['name'] == "TestBot"
        assert d['token'] == "token123"
        assert d['chat_id'] == "123"


class TestBotsReloader:
    """Test BotsReloader class."""

    @pytest.fixture
    def temp_config_file(self, tmp_path):
        """Create a temporary config file."""
        config_path = tmp_path / "bots.yaml"
        config = {
            'bots': [
                {
                    'name': 'TestBot1',
                    'platform': 'telegram',
                    'service_name': 'test_service',
                    'token_env': 'TEST_TOKEN_1',
                    'chat_id_env': 'TEST_CHAT_ID_1'
                },
                {
                    'name': 'TestBot2',
                    'platform': 'telegram',
                    'service_name': 'test_service',
                    'token_env': 'TEST_TOKEN_2',
                    'chat_id_env': 'TEST_CHAT_ID_2'
                }
            ]
        }
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        return str(config_path)

    def test_load_bots_config(self, temp_config_file):
        """Test loading bots configuration."""
        with patch.dict(os.environ, {
            'TEST_TOKEN_1': 'token1',
            'TEST_CHAT_ID_1': 'chat1',
            'TEST_TOKEN_2': 'token2',
            'TEST_CHAT_ID_2': 'chat2'
        }):
            reloader = BotsReloader(temp_config_file, MagicMock())
            bots = reloader.load_bots_config()

            assert len(bots) == 2
            assert bots[0].name == 'TestBot1'
            assert bots[0].token == 'token1'
            assert bots[1].name == 'TestBot2'
            assert bots[1].token == 'token2'

    def test_detect_changes_added(self, temp_config_file):
        """Test detecting added bots."""
        reloader = BotsReloader(temp_config_file, MagicMock())
        reloader._current_bots = {'TestBot1': BotConfig('TestBot1', 'token1')}

        new_bots = [
            BotConfig('TestBot1', 'token1'),
            BotConfig('TestBot2', 'token2'),
        ]

        added, removed, changed = reloader._detect_changes(new_bots)

        assert len(added) == 1
        assert added[0].name == 'TestBot2'
        assert len(removed) == 0
        assert len(changed) == 0

    def test_detect_changes_removed(self, temp_config_file):
        """Test detecting removed bots."""
        reloader = BotsReloader(temp_config_file, MagicMock())
        reloader._current_bots = {
            'TestBot1': BotConfig('TestBot1', 'token1'),
            'TestBot2': BotConfig('TestBot2', 'token2')
        }

        new_bots = [
            BotConfig('TestBot1', 'token1'),
        ]

        added, removed, changed = reloader._detect_changes(new_bots)

        assert len(added) == 0
        assert len(removed) == 1
        assert 'TestBot2' in removed
        assert len(changed) == 0

    def test_detect_changes_changed(self, temp_config_file):
        """Test detecting changed bots."""
        reloader = BotsReloader(temp_config_file, MagicMock())
        reloader._current_bots = {'TestBot1': BotConfig('TestBot1', 'token1')}

        new_bots = [
            BotConfig('TestBot1', 'token2'),  # Same name, different token
        ]

        added, removed, changed = reloader._detect_changes(new_bots)

        assert len(added) == 0
        assert len(removed) == 0
        assert len(changed) == 1
        assert changed[0].token == 'token2'

    def test_compute_hash(self, temp_config_file):
        """Test configuration hash computation."""
        reloader = BotsReloader(temp_config_file, MagicMock())

        bots1 = [{'name': 'Bot1', 'token_env': 'TOKEN1'}, {'name': 'Bot2', 'token_env': 'TOKEN2'}]
        bots2 = [{'name': 'Bot2', 'token_env': 'TOKEN2'}, {'name': 'Bot1', 'token_env': 'TOKEN1'}]
        bots3 = [{'name': 'Bot1', 'token_env': 'TOKEN1'}]

        hash1 = reloader._compute_hash(bots1)
        hash2 = reloader._compute_hash(bots2)
        hash3 = reloader._compute_hash(bots3)

        # Same bots, different order should have same hash
        assert hash1 == hash2
        # Different bots should have different hash
        assert hash1 != hash3


class TestHotReloadIntegration:
    """Integration tests for hot reload."""

    @pytest.fixture
    def mock_env(self):
        """Setup mock environment."""
        env = {
            'TEST_TOKEN_1': 'token_abc',
            'TEST_CHAT_ID_1': 'chat_123',
            'TEST_TOKEN_2': 'token_def',
            'TEST_CHAT_ID_2': 'chat_456'
        }
        with patch.dict(os.environ, env):
            yield

    def test_no_crash_on_missing_file(self):
        """Test that missing config file doesn't crash."""
        reloader = BotsReloader('/nonexistent/config.yaml', MagicMock())
        bots = reloader.load_bots_config()
        assert bots == []

    @pytest.mark.asyncio
    async def test_callback_invoked(self, tmp_path, mock_env):
        """Test that callback is invoked on config change."""
        # Create temp config file
        config_path = tmp_path / "bots.yaml"
        config = {
            'bots': [
                {
                    'name': 'TestBot1',
                    'platform': 'telegram',
                    'service_name': 'test_service',
                    'token_env': 'TEST_TOKEN_1',
                    'chat_id_env': 'TEST_CHAT_ID_1'
                },
                {
                    'name': 'TestBot2',
                    'platform': 'telegram',
                    'service_name': 'test_service',
                    'token_env': 'TEST_TOKEN_2',
                    'chat_id_env': 'TEST_CHAT_ID_2'
                }
            ]
        }
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        callback = MagicMock()
        reloader = BotsReloader(str(config_path), callback)

        # Load initial config
        initial_bots = reloader.load_bots_config()
        reloader._current_bots = {b.name: b for b in initial_bots}

        # Add a new bot to config
        config['bots'].append({
            'name': 'TestBot3',  # New bot
            'platform': 'telegram',
            'service_name': 'test_service',
            'token_env': 'TEST_TOKEN_1',  # Reuse token
            'chat_id_env': 'TEST_CHAT_ID_1'
        })
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        # Trigger reload
        await reloader._trigger_reload()

        # Verify callback was called
        callback.assert_called_once()

        # Verify added bots
        call_args = callback.call_args
        added_bots = call_args[0][0]
        assert len(added_bots) == 1
        assert added_bots[0].name == 'TestBot3'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
