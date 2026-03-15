"""Traffic Monitoring API Routes."""

import time
from fastapi import APIRouter, Request, HTTPException
from typing import Any

router = APIRouter()

# These will be set by main.py
traffic_monitor = None


def init_traffic_routes(monitor):
    """Initialize traffic routes with dependencies."""
    global traffic_monitor
    traffic_monitor = monitor


@router.get("/traffic")
async def get_traffic_stats() -> dict[str, Any]:
    """Get current traffic statistics."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    stats = await traffic_monitor.get_current_stats()
    return {
        "status": "ok",
        "data": stats,
        "timestamp": int(time.time()),
    }


@router.get("/traffic/history")
async def get_traffic_history(minutes: int = 60) -> dict[str, Any]:
    """Get traffic history for the past N minutes."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    history = await traffic_monitor.get_history(minutes)
    return {
        "status": "ok",
        "history": history,
        "count": len(history),
        "timestamp": int(time.time()),
    }


@router.get("/traffic/endpoints")
async def get_top_endpoints(limit: int = 5) -> dict[str, Any]:
    """Get top API endpoints by request count."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    endpoints = await traffic_monitor.get_top_endpoints(limit)
    return {
        "status": "ok",
        "endpoints": [
            {"endpoint": ep[0], "count": ep[1]}
            for ep in endpoints
        ],
        "timestamp": int(time.time()),
    }


@router.get("/traffic/message-types")
async def get_message_types() -> dict[str, Any]:
    """Get IPC message type distribution."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    distribution = await traffic_monitor.get_message_type_distribution()
    return {
        "status": "ok",
        "message_types": distribution,
        "timestamp": int(time.time()),
    }


@router.post("/traffic/record-ipc")
async def record_ipc_message(request: Request) -> dict[str, Any]:
    """Record an IPC message (internal use)."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    try:
        data = await request.json()
        await traffic_monitor.record_ipc_message(
            direction=data.get("direction", "unknown"),
            msg_type=data.get("msg_type", "unknown"),
            size_bytes=data.get("size_bytes", 0),
            error=data.get("error", False),
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/traffic/record-api")
async def record_api_request(request: Request) -> dict[str, Any]:
    """Record an API request (internal use)."""
    if not traffic_monitor:
        raise HTTPException(status_code=503, detail="Traffic monitor not initialized")

    try:
        data = await request.json()
        await traffic_monitor.record_api_request(
            endpoint=data.get("endpoint", "unknown"),
            response_time_ms=data.get("response_time_ms", 0),
            error=data.get("error", False),
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
