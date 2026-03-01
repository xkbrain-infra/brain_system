"""Server-Sent Events for Agent Dashboard."""

import asyncio
import json
import time
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

router = APIRouter()

# Will be set by main.py
collector = None


def init_sse(c):
    """Initialize SSE with collector."""
    global collector
    collector = c


async def event_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events."""
    last_data = None

    while True:
        try:
            if collector:
                agents = collector.last_agents
                now = int(time.time())

                # Enrich data
                enriched = []
                for agent in agents:
                    a = dict(agent)
                    registered_at = a.get("registered_at", 0)
                    last_heartbeat = a.get("last_heartbeat", 0)
                    a["uptime_seconds"] = now - registered_at if registered_at else 0
                    a["heartbeat_age_seconds"] = now - last_heartbeat if last_heartbeat else 0
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
