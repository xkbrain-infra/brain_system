"""Unit tests for message converter."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from message_converter import MessageConverter


def test_text_message_conversion():
    """Test converting text message."""
    update = {
        'update_id': 123,
        'message': {
            'message_id': 456,
            'from': {'id': 789, 'username': 'testuser'},
            'chat': {'id': 789, 'type': 'private'},
            'date': 1707984000,
            'text': 'Hello bot'
        }
    }

    msg = MessageConverter.convert(update)
    assert msg.content_type == 'text'
    assert msg.content == 'Hello bot'
    assert msg.user_id == '789'
    assert msg.platform == 'telegram'
    print("✓ test_text_message_conversion passed")


def test_photo_message_conversion():
    """Test converting photo message."""
    update = {
        'update_id': 124,
        'message': {
            'message_id': 457,
            'from': {'id': 790, 'username': 'testuser2'},
            'chat': {'id': 790, 'type': 'private'},
            'date': 1707984000,
            'photo': [
                {'file_id': 'AgADAgADxxx', 'file_unique_id': 'yyy', 'width': 100, 'height': 100}
            ]
        }
    }

    msg = MessageConverter.convert(update)
    assert msg.content_type == 'photo'
    assert len(msg.attachments) > 0
    print("✓ test_photo_message_conversion passed")


def test_timestamp_formatting():
    """Test ISO8601 timestamp formatting."""
    update = {
        'update_id': 125,
        'message': {
            'message_id': 458,
            'from': {'id': 791, 'username': 'testuser3'},
            'chat': {'id': 791, 'type': 'private'},
            'date': 1707984000,
            'text': 'Test'
        }
    }

    msg = MessageConverter.convert(update)
    assert msg.timestamp.endswith('Z')
    assert 'T' in msg.timestamp  # ISO format
    print("✓ test_timestamp_formatting passed")


if __name__ == '__main__':
    test_text_message_conversion()
    test_photo_message_conversion()
    test_timestamp_formatting()
    print("\n✅ All tests passed!")
