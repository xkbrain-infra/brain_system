"""Alert fallback chain for health monitor notifications."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from timer.daemon_client import IPCError


ALERT_LOG_PATH = "/xkagent_infra/runtime/logs/health_alerts.log"
DEFAULT_CHANNELS = ["telegram", "email", "file_log"]
TIMER_AGENT_NAME = "service-brain_timer"


async def alert_fallback(
    daemon_client: Any,
    alert_message: str,
    alert_level: str,
    target: str,
    channels: list[str] | None = None,
) -> dict[str, Any]:
    """Send alert via fallback chain.

    Email is intentionally a Phase 1 placeholder and always skipped.
    """
    requested_channels = channels or list(DEFAULT_CHANNELS)
    ordered_channels = [c for c in requested_channels if c]
    if "file_log" not in ordered_channels:
        ordered_channels.append("file_log")

    for channel in ordered_channels:
        if channel == "telegram":
            if not await _is_agent_online(daemon_client, "service-telegram_api"):
                continue
            try:
                await asyncio.to_thread(
                    daemon_client.send,
                    from_agent=TIMER_AGENT_NAME,
                    to_agent="service-telegram_api",
                    payload={
                        "event_type": "ALERT_NOTIFICATION",
                        "content": alert_message,
                        "alert_level": alert_level,
                        "target": target,
                    },
                    message_type="request",
                )
                return {"channel_used": "telegram", "success": True}
            except IPCError:
                continue
        elif channel == "email":
            # Phase 1 decision: keep the extension point but skip implementation.
            continue
        elif channel == "file_log":
            _write_alert_log(alert_message, alert_level, target)
            return {"channel_used": "file_log", "success": True}

    return {"channel_used": "", "success": False}


async def _is_agent_online(
    daemon_client: Any,
    agent_name: str,
    max_idle_seconds: float = 30.0,
) -> bool:
    try:
        result = await asyncio.to_thread(daemon_client.list_agents, True)
    except Exception:
        return False
    if not isinstance(result, dict):
        return False
    agents = result.get("agents", [])
    if not isinstance(agents, list):
        return False
    for info in agents:
        if not isinstance(info, dict):
            continue
        if str(info.get("name", "")).strip() != agent_name:
            continue
        online = bool(info.get("online", False))
        try:
            idle = float(info.get("idle_seconds", 0) or 0)
        except (TypeError, ValueError):
            idle = float("inf")
        return online and idle < max_idle_seconds
    return False


def _write_alert_log(message: str, level: str, target: str) -> None:
    """Write alert to local file as final fallback."""
    os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "target": target,
        "message": message,
    }
    with open(ALERT_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
