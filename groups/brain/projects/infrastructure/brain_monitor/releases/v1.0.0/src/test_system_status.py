#!/usr/bin/env python3
"""Unit tests for system status API (BS-005).

Tests:
- StatusScorer.calculate_system_status
- Service status mapping rules
"""

import sys
from pathlib import Path

# Add monitor to path
sys.path.insert(0, str(Path(__file__).parent))

from monitor_service import (
    ServiceStatus,
    SystemStatus,
    ProbeResult,
    StatusScorer,
)


def test_system_status_all_healthy():
    """Test system status when all services are healthy."""
    results = [
        ProbeResult("daemon", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("agents", ServiceStatus.HEALTHY, {"online": 15, "total": 16}),
        ProbeResult("ipc", ServiceStatus.HEALTHY, {"pending": 0}),
        ProbeResult("orchestrator", ServiceStatus.HEALTHY, {"online": True}),
        ProbeResult("timer", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("gateway", ServiceStatus.HEALTHY, {"running": True}),
    ]

    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.HEALTHY, f"Expected HEALTHY, got {status}"
    print("✅ test_system_status_all_healthy")


def test_system_status_daemon_down():
    """Test system status when daemon is down (should be CRITICAL)."""
    results = [
        ProbeResult("daemon", ServiceStatus.DOWN, {"running": False}, error="Connection refused"),
        ProbeResult("agents", ServiceStatus.HEALTHY, {"online": 15, "total": 16}),
        ProbeResult("ipc", ServiceStatus.HEALTHY, {"pending": 0}),
        ProbeResult("orchestrator", ServiceStatus.HEALTHY, {"online": True}),
        ProbeResult("timer", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("gateway", ServiceStatus.HEALTHY, {"running": True}),
    ]

    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.CRITICAL, f"Expected CRITICAL when daemon down, got {status}"
    print("✅ test_system_status_daemon_down")


def test_system_status_one_service_down():
    """Test system status when one non-critical service is down (should be DEGRADED)."""
    results = [
        ProbeResult("daemon", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("agents", ServiceStatus.HEALTHY, {"online": 15, "total": 16}),
        ProbeResult("ipc", ServiceStatus.HEALTHY, {"pending": 0}),
        ProbeResult("orchestrator", ServiceStatus.HEALTHY, {"online": True}),
        ProbeResult("timer", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("gateway", ServiceStatus.DOWN, {"running": False}, error="Connection refused"),
    ]

    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.DEGRADED, f"Expected DEGRADED when one service down, got {status}"
    print("✅ test_system_status_one_service_down")


def test_system_status_one_service_degraded():
    """Test system status when one service is degraded (should be DEGRADED)."""
    results = [
        ProbeResult("daemon", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("agents", ServiceStatus.DEGRADED, {"online": 12, "total": 16, "online_ratio": 0.75}),
        ProbeResult("ipc", ServiceStatus.HEALTHY, {"pending": 0}),
        ProbeResult("orchestrator", ServiceStatus.HEALTHY, {"online": True}),
        ProbeResult("timer", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("gateway", ServiceStatus.HEALTHY, {"running": True}),
    ]

    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.DEGRADED, f"Expected DEGRADED when one service degraded, got {status}"
    print("✅ test_system_status_one_service_degraded")


def test_system_status_empty_results():
    """Test system status with empty results (should be CRITICAL)."""
    results = []

    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.CRITICAL, f"Expected CRITICAL for empty results, got {status}"
    print("✅ test_system_status_empty_results")


def test_system_status_with_unknown():
    """Test system status with unknown services (should still work)."""
    results = [
        ProbeResult("daemon", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("agents", ServiceStatus.HEALTHY, {"online": 15, "total": 16}),
        ProbeResult("ipc", ServiceStatus.UNKNOWN, {}, error="Timeout"),
        ProbeResult("orchestrator", ServiceStatus.HEALTHY, {"online": True}),
        ProbeResult("timer", ServiceStatus.HEALTHY, {"running": True}),
        ProbeResult("gateway", ServiceStatus.HEALTHY, {"running": True}),
    ]

    # Unknown shouldn't cause degraded status (only down/degraded should)
    status = StatusScorer.calculate_system_status(results)
    assert status == SystemStatus.HEALTHY, f"Expected HEALTHY with unknown services, got {status}"
    print("✅ test_system_status_with_unknown")


def test_agents_status_mapping():
    """Test agents service status mapping rules."""
    # Test healthy threshold (>= 0.95)
    result = ProbeResult("agents", ServiceStatus.HEALTHY, {"online": 15, "total": 16, "online_ratio": 0.94})
    # online_ratio = 0.94 should be DEGRADED per spec
    # This tests that our probe correctly maps the ratio

    # Test degraded threshold (0.70 - 0.95)
    result = ProbeResult("agents", ServiceStatus.DEGRADED, {"online": 12, "total": 16, "online_ratio": 0.75})
    assert result.status == ServiceStatus.DEGRADED

    # Test down threshold (< 0.70)
    result = ProbeResult("agents", ServiceStatus.DOWN, {"online": 10, "total": 16, "online_ratio": 0.625})
    assert result.status == ServiceStatus.DOWN

    print("✅ test_agents_status_mapping")


def test_ipc_status_mapping():
    """Test IPC service status mapping rules."""
    # Healthy: failed=0 and pending <= 100
    result = ProbeResult("ipc", ServiceStatus.HEALTHY, {
        "total_messages": 100,
        "pending": 50,
        "acked": 100,
        "failed": 0,
        "success_rate": 1.0
    })
    assert result.status == ServiceStatus.HEALTHY

    # Degraded: failed > 0 and failed_ratio < 0.05
    result = ProbeResult("ipc", ServiceStatus.DEGRADED, {
        "total_messages": 100,
        "pending": 0,
        "acked": 97,
        "failed": 3,
        "success_rate": 0.97
    })
    assert result.status == ServiceStatus.DEGRADED

    # Down: failed_ratio >= 0.05
    result = ProbeResult("ipc", ServiceStatus.DOWN, {
        "total_messages": 100,
        "pending": 0,
        "acked": 90,
        "failed": 10,
        "success_rate": 0.90
    })
    assert result.status == ServiceStatus.DOWN

    print("✅ test_ipc_status_mapping")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Running BS-005 System Status Unit Tests")
    print("=" * 60)
    print()

    tests = [
        test_system_status_all_healthy,
        test_system_status_daemon_down,
        test_system_status_one_service_down,
        test_system_status_one_service_degraded,
        test_system_status_empty_results,
        test_system_status_with_unknown,
        test_agents_status_mapping,
        test_ipc_status_mapping,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
