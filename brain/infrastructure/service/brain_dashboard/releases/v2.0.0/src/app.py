"""Dashboard Web Application - T10 Integration.

FastAPI application serving both API and static web assets.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketState

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
    return {"status": "ok", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
