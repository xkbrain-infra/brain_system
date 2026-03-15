"""Server-Sent Events for Agent Dashboard."""

import asyncio
import json
import time
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

router = APIRouter()

# Registry API endpoint
REGISTRY_URL = "http://localhost:8080/api/v2/registry/agents"


async def fetch_agents() -> list:
    """Fetch agents from registry API."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(REGISTRY_URL)
            if response.status_code == 200:
                data = response.json()
                return data.get("agents", [])
    except Exception as e:
        print(f"SSE fetch error: {e}")
    return []


async def event_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events."""
    last_data = None

    while True:
        try:
            agents = await fetch_agents()
            now = int(time.time())

            # Enrich data for frontend
            enriched = []
            for agent in agents:
                a = dict(agent)
                # Map status to online boolean
                a["online"] = a.get("status") == "active"
                # Use name as instance_id if not present
                if not a.get("instance_id"):
                    a["instance_id"] = a.get("name", "unknown")
                # Calculate fake uptime (since registry doesn't have registered_at)
                a["uptime_seconds"] = 0
                a["heartbeat_age_seconds"] = 0
                enriched.append(a)

            data = {
                "agents": enriched,
                "count": len(enriched),
                "online_count": sum(1 for a in enriched if a.get("online")),
                "timestamp": now,
            }

            # Only send if data changed or every 30s as heartbeat
            data_json = json.dumps(data, ensure_ascii=False)
            if data_json != last_data or True:  # Always send for now
                last_data = data_json
                yield f"data: {data_json}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        await asyncio.sleep(5)  # Update every 5 seconds


@router.get("/api/sse")
async def sse_endpoint():
    """SSE endpoint for real-time updates."""
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
