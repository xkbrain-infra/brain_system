#!/usr/bin/env python3
"""Test script for IPC Reliability module."""

import json
import sys
import time

sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service")

from timer.ipc_reliability import MessageStateStore, MessageStatus
from timer.daemon_client import DaemonClient


def test_state_store():
    """Test MessageStateStore basic operations."""
    print("=" * 50)
    print("Testing MessageStateStore")
    print("=" * 50)

    store = MessageStateStore(
        db_path="/tmp/test_ipc_state.db",
        timeout_seconds=2,
        max_retries=3,
        retry_backoff_seconds=1,
    )

    # Test record_send
    msg_id = store.generate_message_id()
    print(f"\n1. Recording send: {msg_id}")
    state = store.record_send(
        message_id=msg_id,
        from_agent="test_sender",
        target="test_receiver",
        payload=json.dumps({"test": "data"}),
        message_type="request",
    )
    print(f"   Status: {state.status.value}")
    print(f"   Deadline: {state.deadline_at - state.sent_at:.1f}s from now")
    assert state.status == MessageStatus.SENT

    # Test get_by_id
    print(f"\n2. Get by ID: {msg_id}")
    fetched = store.get_by_id(msg_id)
    assert fetched is not None
    assert fetched.status == MessageStatus.SENT
    print(f"   Found: {fetched.status.value}")

    # Test timeout detection
    print("\n3. Waiting for timeout (2s)...")
    time.sleep(2.5)
    pending = store.get_pending_timeouts()
    assert len(pending) > 0
    print(f"   Pending timeouts: {len(pending)}")
    for p in pending:
        print(f"   - {p.message_id[:8]}... status={p.status.value}")

    # Test mark_retried
    print(f"\n4. Marking retry for: {msg_id}")
    updated, new_deadline = store.mark_retried(msg_id)
    assert updated
    print(f"   Retried: {updated}, new deadline in {new_deadline - time.time():.1f}s")

    fetched = store.get_by_id(msg_id)
    assert fetched.status == MessageStatus.RETRIED
    assert fetched.attempt_count == 2
    print(f"   Status: {fetched.status.value}, attempt: {fetched.attempt_count}")

    # Test mark_acked
    print(f"\n5. Marking acked for: {msg_id}")
    acked = store.mark_acked(msg_id, "test ack")
    assert acked
    fetched = store.get_by_id(msg_id)
    assert fetched.status == MessageStatus.ACKED
    print(f"   Status: {fetched.status.value}")

    # Test stats
    print("\n6. Getting stats:")
    stats = store.get_stats()
    print(f"   Total: {stats['total']}")
    print(f"   By status: {stats['by_status']}")
    print(f"   Pending: {stats['pending']}")
    print(f"   Acked: {stats['acked']}")
    print(f"   Failed: {stats['failed']}")

    # Test max retries exceeded
    print("\n7. Testing max retries (3 attempts):")
    msg_id2 = store.generate_message_id()
    store.record_send(
        message_id=msg_id2,
        from_agent="test_sender",
        target="unreachable_target",
        payload="{}",
        timeout_override=0.1,
    )
    time.sleep(0.2)

    for i in range(4):
        updated, _ = store.mark_retried(msg_id2)
        fetched = store.get_by_id(msg_id2)
        print(f"   Retry {i+1}: updated={updated}, status={fetched.status.value}, attempts={fetched.attempt_count}")
        if not updated:
            break
        time.sleep(0.2)

    assert fetched.status == MessageStatus.FAILED
    print(f"   Final status: {fetched.status.value} (max retries exceeded)")

    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)


def test_daemon_tracked_send():
    """Test DaemonClient.tracked_send with real daemon."""
    print("\n" + "=" * 50)
    print("Testing DaemonClient.tracked_send")
    print("=" * 50)

    store = MessageStateStore(
        db_path="/xkagent_infra/brain/infrastructure/data/db/ipc_state.db",
        timeout_seconds=30,
        max_retries=3,
    )
    client = DaemonClient()

    # Check daemon connectivity
    print("\n1. Checking daemon connectivity...")
    if not client.ping():
        print("   SKIP: Daemon not available")
        return

    print("   Daemon is available")

    # Test tracked send
    print("\n2. Sending tracked message...")
    msg_id, resp = client.tracked_send(
        from_agent="test_reliability",
        to_agent="service-agent-orchestrator",
        payload={"test": "reliability_test", "ts": time.time()},
        state_store=store,
        message_type="request",
        timeout_override=30,
    )
    print(f"   Message ID: {msg_id}")
    print(f"   Response: {resp.get('status')}")

    # Check state
    state = store.get_by_id(msg_id)
    print(f"   State: {state.status.value if state else 'NOT FOUND'}")

    # Mark as acked (simulate receiver ack)
    print("\n3. Simulating ack...")
    store.mark_acked(msg_id, "test ack")
    state = store.get_by_id(msg_id)
    print(f"   Final state: {state.status.value}")

    print("\n" + "=" * 50)
    print("Tracked send test complete!")
    print("=" * 50)


if __name__ == "__main__":
    test_state_store()
    test_daemon_tracked_send()
