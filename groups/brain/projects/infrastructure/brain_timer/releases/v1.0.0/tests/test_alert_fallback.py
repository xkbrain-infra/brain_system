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
from timer.daemon_client import IPCError


class FakeDaemonClient:
    def __init__(
        self,
        fail_telegram: bool = False,
        telegram_online: bool = True,
        telegram_idle_seconds: float = 0.0,
    ) -> None:
        self.fail_telegram = fail_telegram
        self.telegram_online = telegram_online
        self.telegram_idle_seconds = telegram_idle_seconds
        self.calls: list[dict] = []

    def list_agents(self, include_offline: bool = False):  # type: ignore[no-untyped-def]
        return {
            "agents": [
                {
                    "name": "service-telegram_api",
                    "online": self.telegram_online,
                    "idle_seconds": self.telegram_idle_seconds,
                }
            ]
        }

    def send(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self.fail_telegram and kwargs.get("to_agent") == "service-telegram_api":
            raise IPCError("telegram offline")
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_alert_fallback_uses_telegram_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    client = FakeDaemonClient(fail_telegram=False)

    result = await alert_mod.alert_fallback(
        daemon_client=client,
        alert_message="[ALERT] test",
        alert_level="critical",
        target="service-foo",
    )

    assert result == {"channel_used": "telegram", "success": True}
    assert len(client.calls) == 1
    assert client.calls[0]["to_agent"] == "service-telegram_api"
    assert not log_path.exists()


@pytest.mark.asyncio
async def test_alert_fallback_falls_back_to_file_log_when_telegram_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    client = FakeDaemonClient(fail_telegram=True)

    result = await alert_mod.alert_fallback(
        daemon_client=client,
        alert_message="[ALERT] fallback",
        alert_level="warning",
        target="service-bar",
    )

    assert result == {"channel_used": "file_log", "success": True}
    assert len(client.calls) == 1
    assert log_path.exists()

    line = log_path.read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["level"] == "warning"
    assert payload["target"] == "service-bar"
    assert payload["message"] == "[ALERT] fallback"
    assert payload["timestamp"].endswith("Z")


@pytest.mark.asyncio
async def test_alert_fallback_falls_back_to_file_log_when_telegram_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    client = FakeDaemonClient(telegram_online=False)

    result = await alert_mod.alert_fallback(
        daemon_client=client,
        alert_message="[ALERT] offline",
        alert_level="critical",
        target="service-telegram_api",
        channels=["telegram", "file_log"],
    )

    assert result == {"channel_used": "file_log", "success": True}
    assert len(client.calls) == 0
    assert log_path.exists()


@pytest.mark.asyncio
async def test_alert_fallback_falls_back_when_telegram_stale_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    client = FakeDaemonClient(telegram_online=True, telegram_idle_seconds=45.0)

    result = await alert_mod.alert_fallback(
        daemon_client=client,
        alert_message="[ALERT] stale idle",
        alert_level="critical",
        target="service-telegram_api",
        channels=["telegram", "file_log"],
    )

    assert result == {"channel_used": "file_log", "success": True}
    assert len(client.calls) == 0
    assert log_path.exists()


@pytest.mark.asyncio
async def test_alert_fallback_skips_email_placeholder_and_still_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "health_alerts.log"
    monkeypatch.setattr(alert_mod, "ALERT_LOG_PATH", str(log_path))
    client = FakeDaemonClient(fail_telegram=False)

    result = await alert_mod.alert_fallback(
        daemon_client=client,
        alert_message="[ALERT] email placeholder",
        alert_level="critical",
        target="agent-foo",
        channels=["email"],
    )

    assert result == {"channel_used": "file_log", "success": True}
    assert len(client.calls) == 0
    assert log_path.exists()
