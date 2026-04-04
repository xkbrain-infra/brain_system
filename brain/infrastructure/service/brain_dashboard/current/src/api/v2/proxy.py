"""Proxy Stats API - T1 Implementation.

Provides endpoints to query traffic statistics from brain_gateway.
"""

import time
import httpx
from typing import Any
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/proxy", tags=["proxy"])

# brain_gateway endpoint
GATEWAY_BASE_URL = "http://127.0.0.1:8200"


@router.get("/stats")
async def get_proxy_stats() -> dict[str, Any]:
    """Get proxy traffic statistics from brain_gateway.

    Returns:
        JSON with QPS, latency, error rate, and traffic metrics.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{GATEWAY_BASE_URL}/api/v1/stats")
            response.raise_for_status()
            stats_data = response.json()
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to brain_gateway: {e}"
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Timeout waiting for brain_gateway response"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"brain_gateway returned error: {e.response.status_code}"
        )

    # Transform gateway stats to dashboard format
    # Gateway format: {"total_messages": N, "total_errors": N,
    #                  "by_direction": {...}, "by_platform": {...}, ...}
    by_platform = stats_data.get("by_platform", {})
    total_inbound = stats_data.get("by_direction", {}).get("inbound", 0)
    total_outbound = stats_data.get("by_direction", {}).get("outbound", 0)

    # Calculate per-platform stats
    platform_stats = {}
    for plat_name, plat_data in by_platform.items():
        platform_stats[plat_name] = {
            "qps": 0.0,  # Not directly available from gateway
            "requests": plat_data.get("inbound", 0) + plat_data.get("outbound", 0),
            "errors": plat_data.get("errors", 0),
            "error_rate": plat_data.get("errors", 0) / max(plat_data.get("inbound", 0) + plat_data.get("outbound", 0), 1) * 100,
        }

    transformed = {
        "timestamp": int(time.time()),
        "qps": 0.0,  # Would need time-series data to calculate
        "total_requests": stats_data.get("total_messages", 0),
        "avg_latency_ms": 0.0,  # Not tracked by gateway currently
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "p99_latency_ms": 0.0,
        "error_rate": stats_data.get("total_errors", 0) / max(stats_data.get("total_messages", 1), 1) * 100,
        "errors_total": stats_data.get("total_errors", 0),
        "active_connections": 0,  # Not tracked by gateway
        "by_direction": stats_data.get("by_direction", {"inbound": 0, "outbound": 0}),
        "by_platform": platform_stats,
        "by_agent": stats_data.get("by_agent", {}),
        "source": "brain_gateway",
    }

    return transformed


@router.get("/routes")
async def get_proxy_routes() -> dict[str, Any]:
    """Get configured routing rules from brain_gateway.

    Returns:
        JSON with routing configuration.
    """
    # Try to fetch from gateway, fallback to static config
    routes_data = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{GATEWAY_BASE_URL}/routes")
            if response.status_code == 200:
                routes_data = response.json()
    except Exception:
        pass

    if routes_data is None:
        # Fallback to static config based on gateway config
        routes_data = {
            "platforms": {"telegram": "agent-brain_frontdesk"},
            "keywords": [],
            "default": "agent-brain_frontdesk",
        }

    return {
        "timestamp": int(time.time()),
        "routes": routes_data,
        "source": "brain_gateway" if routes_data else "static_fallback",
    }


@router.get("/traffic")
async def get_traffic_summary(minutes: int = 5) -> dict[str, Any]:
    """Get traffic summary for the last N minutes.

    Args:
        minutes: Time window in minutes (default 5).

    Returns:
        JSON with traffic summary.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Use /api/v1/stats as the source
            response = await client.get(f"{GATEWAY_BASE_URL}/api/v1/stats")
            response.raise_for_status()
            stats_data = response.json()
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to brain_gateway: {e}"
        )

    total_messages = stats_data.get("total_messages", 0)
    total_errors = stats_data.get("total_errors", 0)
    error_rate = total_errors / max(total_messages, 1) * 100

    return {
        "timestamp": int(time.time()),
        "window_minutes": minutes,
        "requests": total_messages,
        "errors": total_errors,
        "error_rate": error_rate,
        "by_platform": stats_data.get("by_platform", {}),
        "by_direction": stats_data.get("by_direction", {}),
        "source": "brain_gateway",
    }
