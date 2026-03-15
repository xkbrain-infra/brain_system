"""REST API Routes for Agent Dashboard."""

import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from typing import Any

router = APIRouter()

# These will be set by main.py
storage = None
collector = None
alerter = None
config = None


def init_routes(s, c, a, cfg):
    """Initialize routes with dependencies."""
    global storage, collector, alerter, config
    storage = s
    collector = c
    alerter = a
    config = cfg


@router.get("/api/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    daemon_ok = collector.is_daemon_alive() if collector else False
    return {
        "status": "ok" if daemon_ok else "degraded",
        "daemon": "connected" if daemon_ok else "disconnected",
        "timestamp": int(time.time()),
    }


@router.get("/api/agents")
async def get_agents() -> dict[str, Any]:
    """Get all agents with current state."""
    # Use collector's last data for real-time
    agents = collector.last_agents if collector else []

    # Enrich with computed fields
    now = int(time.time())
    enriched = []
    for agent in agents:
        a = dict(agent)
        registered_at = a.get("registered_at", 0)
        last_heartbeat = a.get("last_heartbeat", 0)

        a["uptime_seconds"] = now - registered_at if registered_at else 0
        a["heartbeat_age_seconds"] = now - last_heartbeat if last_heartbeat else 0
        a["uptime_formatted"] = format_duration(a["uptime_seconds"])
        a["heartbeat_age_formatted"] = format_duration(a["heartbeat_age_seconds"])
        enriched.append(a)

    return {
        "agents": enriched,
        "count": len(enriched),
        "timestamp": now,
    }


@router.get("/api/agents/{agent_name}/history")
async def get_agent_history(agent_name: str, hours: int = 24) -> dict[str, Any]:
    """Get agent history."""
    if not storage:
        raise HTTPException(status_code=503, detail="Storage not initialized")

    history = storage.get_agent_history(agent_name, hours)
    return {
        "agent_name": agent_name,
        "history": history,
        "count": len(history),
    }


@router.get("/api/alerts")
async def get_alerts(limit: int = 50) -> dict[str, Any]:
    """Get recent alerts."""
    if not storage:
        raise HTTPException(status_code=503, detail="Storage not initialized")

    alerts = storage.get_recent_alerts(limit)
    return {
        "alerts": alerts,
        "count": len(alerts),
    }


@router.post("/api/alerts/test")
async def send_test_alert() -> dict[str, Any]:
    """Send a test alert."""
    if not alerter:
        raise HTTPException(status_code=503, detail="Alerter not initialized")

    success = alerter.send_test_alert("Dashboard 告警测试")
    return {
        "status": "ok" if success else "failed",
        "message": "Test alert sent" if success else "Failed to send",
    }


@router.get("/api/stats")
async def get_stats() -> dict[str, Any]:
    """Get dashboard statistics."""
    agents = collector.last_agents if collector else []
    now = int(time.time())

    online_count = sum(1 for a in agents if a.get("online"))
    offline_count = len(agents) - online_count

    return {
        "total_agents": len(agents),
        "online_count": online_count,
        "offline_count": offline_count,
        "timestamp": now,
    }


def format_duration(seconds: int) -> str:
    """Format duration in human readable form."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    elif seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"
