"""Dashboard Web Application - T10 Integration.

FastAPI application serving both API and static web assets.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketState
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dashboard_web")

# Create FastAPI app
app = FastAPI(
    title="XKBrain Infra Dashboard",
    description="XKBrain Infrastructure Management Dashboard",
    version="2.0.0",
)

# Initialize traffic monitor
try:
    from core.traffic_monitor import TrafficMonitor
    from api.v2.traffic import init_traffic_routes

    traffic_monitor = TrafficMonitor()
    init_traffic_routes(traffic_monitor)
    logger.info("Traffic monitor initialized")
except Exception as e:
    logger.warning(f"Failed to initialize traffic monitor: {e}")
    traffic_monitor = None

# Request middleware to track API metrics
@app.middleware("http")
async def traffic_middleware(request: Request, call_next):
    """Track API request metrics."""
    start_time = time.time()
    path = request.url.path

    try:
        response = await call_next(request)
        error = False
    except Exception as e:
        error = True
        raise e
    finally:
        if traffic_monitor:
            response_time = (time.time() - start_time) * 1000  # ms
            # Use asyncio.create_task to avoid blocking
            import asyncio
            asyncio.create_task(traffic_monitor.record_api_request(
                endpoint=path,
                response_time_ms=response_time,
                error=error,
            ))

    return response

# Include API v2 routes
from api.v2 import router as v2_router
app.include_router(v2_router)

# Include v1 routes for backward compatibility
from api.routes import router as v1_router
from api.sse import router as sse_router
app.include_router(v1_router)
app.include_router(sse_router)

# Static web templates path - auto-detect based on script location
SCRIPT_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = SCRIPT_DIR / "web" / "templates"


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve main dashboard HTML."""
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return HTMLResponse(content="<h1>Dashboard</h1><p>Template not found</p>", status_code=500)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0", "traffic_monitor": "initialized" if traffic_monitor else "disabled"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
