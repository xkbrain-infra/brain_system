from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from timer import alert_fallback as alert_mod
from timer import health_sweep as health_mod
from timer.daemon_client import IPCError


def _runbook() -> dict:
    return {
        "health_monitor": {
            "defaults": {
                "threshold_seconds": 120,
                "alert_target": "service-agentctl",
                "alert_channels": ["telegram", "file_log"],
            },
            "targets": {
                "service-telegram_api": {
                    "type": "service",
                    "threshold_seconds": 60,
                    "recovery_enabled": False,
                    "on_failure": {"alert_channels": ["telegram", "file_log"]},
                }
            },
        }
    }


def _runbook_with_recovery() -> dict:
    return {
        "health_monitor": {
            "defaults": {
                "threshold_seconds": 120,
                "alert_target": "service-agentctl",
                "alert_channels": ["telegram", "file_log"],
            },
            "targets": {
                "service-telegram_api": {
                    "type": "service",
                    "threshold_seconds": 60,
                    "recovery_enabled": True,
                    "recovery_steps": [
                        {"action": "supervisorctl_restart", "target": "service_telegram_api"},
                        {"action": "verify", "wait_seconds": 0, "check": "ipc_online"},
                    ],
                    "on_failure": {"alert_channels": ["file_log"], "message": "recovery failed"},
                }
            },
        }
    }


class FakeDaemon:
    def __init__(
        self,
        agents: list[dict] | None = None,
        fail_alert_target: bool = False,
        fail_telegram: bool = False,
        list_error: bool = False,
    ) -> None:
        self.agents = agents or []
        self.fail_alert_target = fail_alert_target
        self.fail_telegram = fail_telegram
        self.list_error = list_error
        self.send_calls: list[dict] = []

    def list_agents(self, include_offline: bool = False):  # type: ignore[no-untyped-def]
        if self.list_error:
            raise IPCError("daemon offline")
        return {"agents": self.agents}

    def send(self, **kwargs):  # type: ignore[no-untyped-def]
        self.send_calls.append(kwargs)
        to_agent = kwargs.get("to_agent")
        if self.fail_alert_target and to_agent == "service-agentctl":
            raise IPCError("alert target offline")
        if self.fail_telegram and to_agent == "service-telegram_api":
            raise IPCError("telegram offline")
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_td1_normal_no_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 980.0}])
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    result = await sweep.sweep()

    assert result == {"alerts": [], "recovered": []}
    assert daemon.send_calls == []


@pytest.mark.asyncio
async def test_td2_timeout_sends_health_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}])
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    result = await sweep.sweep()

    assert result == {"alerts": ["service-telegram_api"], "recovered": []}
    assert len(daemon.send_calls) == 1
    payload = daemon.send_calls[0]["payload"]
    assert daemon.send_calls[0]["to_agent"] == "service-agentctl"
    assert payload["event_type"] == "HEALTH_ALERT"
    assert payload["target"] == "service-telegram_api"
    assert payload["threshold"] == 60.0
    assert payload["idle_seconds"] == 100.0


@pytest.mark.asyncio
async def test_td3_dedup_no_duplicate_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([1_000.0, 1_010.0])
    monkeypatch.setattr(health_mod.time, "time", lambda: next(times))
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}])
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    first = await sweep.sweep()
    second = await sweep.sweep()

    assert first == {"alerts": ["service-telegram_api"], "recovered": []}
    assert second == {"alerts": [], "recovered": []}
    assert len(daemon.send_calls) == 1


@pytest.mark.asyncio
async def test_td4_recovery_sends_health_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([1_000.0, 1_050.0])
    monkeypatch.setattr(health_mod.time, "time", lambda: next(times))
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}])
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    await sweep.sweep()
    daemon.agents = [{"name": "service-telegram_api", "last_heartbeat": 1_040.0}]
    result = await sweep.sweep()

    assert result == {"alerts": [], "recovered": ["service-telegram_api"]}
    assert len(daemon.send_calls) == 2
    recovered_payload = daemon.send_calls[1]["payload"]
    assert recovered_payload["event_type"] == "HEALTH_RECOVERED"
    assert recovered_payload["target"] == "service-telegram_api"
    assert recovered_payload["downtime_seconds"] == 50.0


@pytest.mark.asyncio
async def test_td5_alert_target_offline_calls_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(
        agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}],
        fail_alert_target=True,
    )
    called: dict = {"count": 0}

    async def fake_fallback(**kwargs):  # type: ignore[no-untyped-def]
        called["count"] += 1
        return {"channel_used": "telegram", "success": True}

    monkeypatch.setattr(health_mod, "alert_fallback", fake_fallback)
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    await sweep.sweep()

    assert called["count"] == 1


@pytest.mark.asyncio
async def test_td6_telegram_fails_then_file_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    monkeypatch.setattr(health_mod, "alert_fallback", alert_mod.alert_fallback)

    daemon = FakeDaemon(
        agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}],
        fail_alert_target=True,
        fail_telegram=True,
    )
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    await sweep.sweep()

    assert log_path.exists()
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["target"] == "service-telegram_api"
    assert payload["level"] == "critical"


@pytest.mark.asyncio
async def test_td7_daemon_unreachable_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(list_error=True)
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    result = await sweep.sweep()

    assert result == {"alerts": [], "recovered": []}
    assert daemon.send_calls == []


@pytest.mark.asyncio
async def test_td8_target_not_in_runbook_use_default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(agents=[{"name": "service-unknown", "last_heartbeat": 870.0}])
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    result = await sweep.sweep()

    assert result == {"alerts": ["service-unknown"], "recovered": []}
    assert len(daemon.send_calls) == 1
    payload = daemon.send_calls[0]["payload"]
    assert payload["target"] == "service-unknown"
    assert payload["threshold"] == 120.0


@pytest.mark.asyncio
async def test_fix001_monitor_online_union_runbook_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(
        agents=[
            {"name": "service-telegram_api", "online": False, "last_heartbeat": 900.0},
            {"name": "legacy-offline", "online": False, "last_heartbeat": 100.0},
            {"name": "online-other", "online": True, "last_heartbeat": 800.0},
        ]
    )
    sweep = health_mod.HealthSweep(daemon_client=daemon, runbook_config=_runbook(), agent_name="service-brain_timer")

    result = await sweep.sweep()

    assert result == {"alerts": ["online-other", "service-telegram_api"], "recovered": []}
    assert len(daemon.send_calls) == 2
    alerted_targets = sorted(call["payload"]["target"] for call in daemon.send_calls)
    assert alerted_targets == ["online-other", "service-telegram_api"]


@pytest.mark.asyncio
async def test_fix004_recovery_success_sends_health_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}])
    sweep = health_mod.HealthSweep(
        daemon_client=daemon,
        runbook_config=_runbook_with_recovery(),
        agent_name="service-brain_timer",
    )

    async def fake_execute_recovery(target, steps):  # type: ignore[no-untyped-def]
        return True

    monkeypatch.setattr(sweep, "_execute_recovery", fake_execute_recovery)
    result = await sweep.sweep()

    assert result == {"alerts": ["service-telegram_api"], "recovered": []}
    event_types = [call["payload"]["event_type"] for call in daemon.send_calls]
    assert event_types == ["HEALTH_ALERT", "HEALTH_RECOVERED"]
    assert sweep.alert_state == {}


@pytest.mark.asyncio
async def test_fix004_recovery_failure_calls_alert_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_mod.time, "time", lambda: 1_000.0)
    daemon = FakeDaemon(agents=[{"name": "service-telegram_api", "last_heartbeat": 900.0}])
    sweep = health_mod.HealthSweep(
        daemon_client=daemon,
        runbook_config=_runbook_with_recovery(),
        agent_name="service-brain_timer",
    )
    called = {"count": 0}

    async def fake_execute_recovery(target, steps):  # type: ignore[no-untyped-def]
        return False

    async def fake_fallback(**kwargs):  # type: ignore[no-untyped-def]
        called["count"] += 1
        return {"channel_used": "file_log", "success": True}

    monkeypatch.setattr(sweep, "_execute_recovery", fake_execute_recovery)
    monkeypatch.setattr(health_mod, "alert_fallback", fake_fallback)
    await sweep.sweep()

    assert called["count"] == 1
