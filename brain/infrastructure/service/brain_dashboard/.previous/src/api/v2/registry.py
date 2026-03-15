"""Registry Viewer API - T2 Implementation.

Provides endpoints to view service and agent registry information.
"""

import time
import yaml
from typing import Any
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/registry", tags=["registry"])

# Registry file path
REGISTRY_PATH = "/brain/infrastructure/config/agentctl/agents_registry.yaml"

# Cache
_registry_cache: dict[str, Any] | None = None
_cache_mtime: float = 0.0
CACHE_TTL_SECONDS = 5  # Reload every 5 seconds max


def load_registry() -> dict[str, Any]:
    """Load agents registry from YAML file with caching.

    Returns:
        Parsed registry data.
    """
    global _registry_cache, _cache_mtime

    path = Path(REGISTRY_PATH)
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Registry file not found: {REGISTRY_PATH}"
        )

    # Check if cache is valid
    current_mtime = path.stat().st_mtime
    if _registry_cache is not None and (time.time() - _cache_mtime) < CACHE_TTL_SECONDS:
        return _registry_cache

    # Reload from file
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        _registry_cache = data or {}
        _cache_mtime = time.time()
        return _registry_cache
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse registry YAML: {e}"
        )


@router.get("/services")
async def get_services() -> dict[str, Any]:
    """Get list of registered services.

    Returns:
        JSON with service list from registry.
    """
    registry = load_registry()

    # Extract services from top-level "services" key
    # Structure: services: { category: [ {name: ..., ...}, ... ] }
    services = []
    services_data = registry.get("services", {})

    for category, svc_list in services_data.items():
        if isinstance(svc_list, list):
            for svc in svc_list:
                if isinstance(svc, dict):
                    svc_name = svc.get("name", "")
                    if svc_name:
                        health = svc.get("health", {})
                        services.append({
                            "name": svc_name,
                            "group": f"services/{category}",
                            "description": svc.get("description", ""),
                            "role": svc.get("role", "service"),
                            "status": svc.get("status", "unknown"),
                            "desired_state": svc.get("managed_by", "unknown"),
                            "path": svc.get("binary", ""),
                            "health_endpoint": health.get("endpoint", "-"),
                        })

    # Also check for service-* agents in groups (legacy/compatibility)
    groups = registry.get("groups", {})
    for group_name, agents in groups.items():
        for agent in agents:
            agent_name = agent.get("name", "")
            if agent_name.startswith("service-"):
                services.append({
                    "name": agent_name,
                    "group": group_name,
                    "description": agent.get("description", ""),
                    "role": agent.get("role", "service"),
                    "status": agent.get("status", "unknown"),
                    "desired_state": agent.get("desired_state", "unknown"),
                    "path": agent.get("path", ""),
                })

    return {
        "timestamp": int(time.time()),
        "services": services,
        "count": len(services),
        "source": REGISTRY_PATH,
    }


@router.get("/agents")
async def get_agents() -> dict[str, Any]:
    """Get list of registered agents.

    Returns:
        JSON with agent list from registry.
    """
    registry = load_registry()

    agents = []
    groups = registry.get("groups", {})

    for group_name, group_agents in groups.items():
        for agent in group_agents:
            agent_name = agent.get("name", "")
            # Exclude services, include only agents
            if not agent_name.startswith("service-"):
                agents.append({
                    "name": agent_name,
                    "group": group_name,
                    "description": agent.get("description", ""),
                    "role": agent.get("role", "unknown"),
                    "status": agent.get("status", "unknown"),
                    "desired_state": agent.get("desired_state", "unknown"),
                    "path": agent.get("path", ""),
                    "tmux_session": agent.get("tmux_session", ""),
                    "required": agent.get("required", False),
                })

    return {
        "timestamp": int(time.time()),
        "agents": agents,
        "count": len(agents),
        "source": REGISTRY_PATH,
    }


@router.get("/health")
async def get_registry_health() -> dict[str, Any]:
    """Get registry health summary.

    Returns:
        JSON with health metrics.
    """
    registry = load_registry()
    groups = registry.get("groups", {})

    total_agents = 0
    active_count = 0
    inactive_count = 0
    service_count = 0

    for group_name, agents in groups.items():
        for agent in agents:
            total_agents += 1
            if agent.get("status") == "active":
                active_count += 1
            else:
                inactive_count += 1

            if agent.get("name", "").startswith("service-"):
                service_count += 1

    return {
        "timestamp": int(time.time()),
        "total_agents": total_agents,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "service_count": service_count,
        "group_count": len(groups),
        "version": registry.get("agents_registry", {}).get("version", "unknown"),
        "source": REGISTRY_PATH,
    }


@router.get("/groups")
async def get_groups() -> dict[str, Any]:
    """Get list of agent groups.

    Returns:
        JSON with group information.
    """
    registry = load_registry()
    groups_data = registry.get("groups", {})
    group_meta = registry.get("group_meta", {})

    groups = []
    for name, agents in groups_data.items():
        meta = group_meta.get(name, {})
        groups.append({
            "name": name,
            "type": meta.get("type", "unknown"),
            "description": meta.get("description", ""),
            "agent_count": len(agents),
        })

    return {
        "timestamp": int(time.time()),
        "groups": groups,
        "count": len(groups),
        "source": REGISTRY_PATH,
    }
