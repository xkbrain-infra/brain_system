"""API V2 Module - Phase 1 Core API."""

from fastapi import APIRouter
from . import proxy, registry, logs

# Create v2 router
router = APIRouter(prefix="/api/v2")

# Include sub-routers
router.include_router(proxy.router)
router.include_router(registry.router)
router.include_router(logs.router)
