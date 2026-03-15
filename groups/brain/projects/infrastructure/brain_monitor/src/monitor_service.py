#!/usr/bin/env python3
"""Brain System Monitor Service - Provides monitoring API endpoints.

Endpoints:
- GET /api/agents - List all agents with status
- GET /api/agents/stats - Agent statistics summary
- GET /api/ipc/stats - IPC message queue statistics
- GET /api/health - System health status
"""

import argparse
import asyncio
import json
import logging
import socket
import struct
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
import httpx
import uvicorn

# Add timer module to path for ipc_reliability import
sys.path.insert(0, str(Path(__file__).parent.parent))
from timer.ipc_reliability import MessageStateStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("monitor_service")

# Create FastAPI app
app = FastAPI(
    title="Brain System Monitor",
    description="Monitoring API for Brain System agents and services",
    version="1.0.0",
)

# Global daemon socket path
daemon_socket_path: str = "/tmp/brain_ipc.sock"

# Global IPC state store
ipc_state_store: MessageStateStore | None = None


# ============================================================
# BS-005: System Status API - Data Models
# ============================================================

class ServiceStatus(str, Enum):
    """Service status enum."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class SystemStatus(str, Enum):
    """Overall system status enum."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class ProbeResult:
    """Result from a service probe."""
    service_name: str
    status: ServiceStatus
    data: dict[str, Any]
    error: str | None = None
    elapsed_ms: float = 0.0


# ============================================================
# BS-005-T1: ProbeAdapter Layer and 6 Probes
# ============================================================

class ProbeAdapter(ABC):
    """Base class for service probes."""

    def __init__(self, service_name: str, timeout_ms: float = 150.0):
        self.service_name = service_name
        self.timeout_ms = timeout_ms
        self.logger = logging.getLogger(f"probe.{service_name}")

    async def execute(self) -> ProbeResult:
        """Execute probe with timeout and error handling."""
        start_time = time.time()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self._probe(),
                timeout=self.timeout_ms / 1000.0
            )
            elapsed_ms = (time.time() - start_time) * 1000.0

            return ProbeResult(
                service_name=self.service_name,
                status=result["status"],
                data=result.get("data", {}),
                error=result.get("error"),
                elapsed_ms=elapsed_ms
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start_time) * 1000.0
            self.logger.warning(f"Probe timeout after {elapsed_ms:.1f}ms")
            return ProbeResult(
                service_name=self.service_name,
                status=ServiceStatus.UNKNOWN,
                data={},
                error=f"Timeout after {self.timeout_ms}ms",
                elapsed_ms=elapsed_ms
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000.0
            self.logger.error(f"Probe error: {e}")
            return ProbeResult(
                service_name=self.service_name,
                status=ServiceStatus.UNKNOWN,
                data={},
                error=str(e),
                elapsed_ms=elapsed_ms
            )

    @abstractmethod
    async def _probe(self) -> dict[str, Any]:
        """Actual probe logic to be implemented by subclasses.

        Returns:
            dict with keys: status (ServiceStatus), data (dict), error (str|None)
        """
        pass


class DaemonProbe(ProbeAdapter):
    """Probe for brain daemon service."""

    def __init__(self):
        super().__init__("daemon")

    async def _probe(self) -> dict[str, Any]:
        """Ping daemon socket."""
        result = send_ipc_command("ping")

        if result.get("status") == "ok":
            return {
                "status": ServiceStatus.HEALTHY,
                "data": {"running": True},
                "error": None
            }
        else:
            return {
                "status": ServiceStatus.DOWN,
                "data": {"running": False},
                "error": result.get("error", "Daemon ping failed")
            }


class AgentsProbe(ProbeAdapter):
    """Probe for agents service."""

    def __init__(self):
        super().__init__("agents")

    async def _probe(self) -> dict[str, Any]:
        """Get agent statistics."""
        # Reuse agent_list logic
        result = send_ipc_command("agent_list", {"include_offline": True})

        if result.get("status") != "ok":
            return {
                "status": ServiceStatus.DOWN,
                "data": {"online": 0, "total": 0, "online_ratio": 0.0},
                "error": result.get("error", "Failed to list agents")
            }

        agents = result.get("agents", [])
        total = len(agents)
        online = sum(1 for a in agents if a.get("online", False))
        online_ratio = online / total if total > 0 else 0.0

        # Status mapping per spec
        if online_ratio >= 0.95:
            status = ServiceStatus.HEALTHY
        elif online_ratio >= 0.70:
            status = ServiceStatus.DEGRADED
        else:
            status = ServiceStatus.DOWN

        return {
            "status": status,
            "data": {
                "online": online,
                "total": total,
                "online_ratio": round(online_ratio, 2)
            },
            "error": None
        }


class IPCProbe(ProbeAdapter):
    """Probe for IPC message queue."""

    def __init__(self):
        super().__init__("ipc")

    async def _probe(self) -> dict[str, Any]:
        """Get IPC statistics."""
        global ipc_state_store

        if ipc_state_store is None:
            return {
                "status": ServiceStatus.UNKNOWN,
                "data": {},
                "error": "IPC state store not initialized"
            }

        try:
            stats = ipc_state_store.get_stats()

            total = stats.get("total", 0)
            pending = stats.get("pending", 0)
            acked = stats.get("acked", 0)
            failed = stats.get("failed", 0)

            # Calculate success rate
            success_rate = acked / total if total > 0 else 1.0
            failed_ratio = failed / total if total > 0 else 0.0

            # Status mapping per spec
            if failed == 0 and pending <= 100:
                status = ServiceStatus.HEALTHY
            elif failed > 0 and failed_ratio < 0.05:
                status = ServiceStatus.DEGRADED
            else:
                status = ServiceStatus.DOWN

            return {
                "status": status,
                "data": {
                    "total_messages": total,
                    "pending": pending,
                    "acked": acked,
                    "failed": failed,
                    "success_rate": round(success_rate, 2)
                },
                "error": None
            }
        except Exception as e:
            return {
                "status": ServiceStatus.UNKNOWN,
                "data": {},
                "error": str(e)
            }


class OrchestratorProbe(ProbeAdapter):
    """Probe for agent orchestrator service."""

    def __init__(self):
        super().__init__("orchestrator")

    async def _probe(self) -> dict[str, Any]:
        """Check if orchestrator is online via agent list."""
        result = send_ipc_command("agent_list", {"include_offline": False})

        if result.get("status") != "ok":
            return {
                "status": ServiceStatus.DOWN,
                "data": {"online": False, "source": "agent_list"},
                "error": result.get("error", "Failed to query agent list")
            }

        agents = result.get("agents", [])
        orchestrator_online = any(
            a.get("name") == "service-agent-orchestrator" and a.get("online", False)
            for a in agents
        )

        status = ServiceStatus.HEALTHY if orchestrator_online else ServiceStatus.DOWN

        return {
            "status": status,
            "data": {
                "online": orchestrator_online,
                "source": "agent_list"
            },
            "error": None if orchestrator_online else "Orchestrator not found in agent list"
        }


class TimerProbe(ProbeAdapter):
    """Probe for timer service."""

    def __init__(self):
        super().__init__("timer")

    async def _probe(self) -> dict[str, Any]:
        """Check timer service health endpoint."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://127.0.0.1:8090/health",
                    timeout=0.15  # 150ms
                )

                if response.status_code == 200:
                    data = response.json()
                    health_status = data.get("status", "unknown")

                    # Map timer status to ServiceStatus
                    if health_status in ["ok", "running"]:
                        status = ServiceStatus.HEALTHY
                    elif health_status == "starting":
                        status = ServiceStatus.DEGRADED
                    else:
                        status = ServiceStatus.DOWN

                    return {
                        "status": status,
                        "data": {
                            "running": True,
                            "jobs_loaded": data.get("jobs_loaded")
                        },
                        "error": None
                    }
                else:
                    return {
                        "status": ServiceStatus.DOWN,
                        "data": {"running": False, "jobs_loaded": None},
                        "error": f"HTTP {response.status_code}"
                    }
        except Exception as e:
            return {
                "status": ServiceStatus.DOWN,
                "data": {"running": False, "jobs_loaded": None},
                "error": str(e)
            }


class GatewayProbe(ProbeAdapter):
    """Probe for webhook gateway service."""

    def __init__(self):
        super().__init__("gateway")

    async def _probe(self) -> dict[str, Any]:
        """Check gateway service health endpoint."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://127.0.0.1:8080/health",
                    timeout=0.15  # 150ms
                )

                if response.status_code == 200:
                    data = response.json()
                    health_status = data.get("status", "unknown")

                    # Map gateway status to ServiceStatus
                    if health_status == "ok":
                        status = ServiceStatus.HEALTHY
                    elif health_status == "degraded":
                        status = ServiceStatus.DEGRADED
                    else:
                        status = ServiceStatus.DOWN

                    return {
                        "status": status,
                        "data": {
                            "running": True,
                            "adapters": data.get("adapters")
                        },
                        "error": None
                    }
                else:
                    return {
                        "status": ServiceStatus.DOWN,
                        "data": {"running": False, "adapters": None},
                        "error": f"HTTP {response.status_code}"
                    }
        except Exception as e:
            return {
                "status": ServiceStatus.DOWN,
                "data": {"running": False, "adapters": None},
                "error": str(e)
            }


# ============================================================
# BS-005-T2: SystemStatusAggregator and StatusScorer
# ============================================================

class StatusScorer:
    """Maps probe results to system-level status."""

    @staticmethod
    def calculate_system_status(probe_results: list[ProbeResult]) -> SystemStatus:
        """Calculate overall system status from probe results.

        Logic:
        - If daemon is down → CRITICAL
        - If any service is down → DEGRADED
        - If all services are healthy or degraded → HEALTHY
        - If any service is degraded → DEGRADED
        """
        if not probe_results:
            return SystemStatus.CRITICAL

        # Extract statuses by service
        statuses_by_service = {
            result.service_name: result.status
            for result in probe_results
        }

        # Critical condition: daemon down
        daemon_status = statuses_by_service.get("daemon")
        if daemon_status == ServiceStatus.DOWN:
            return SystemStatus.CRITICAL

        # Check for any down services
        has_down = any(
            status == ServiceStatus.DOWN
            for status in statuses_by_service.values()
        )
        if has_down:
            return SystemStatus.DEGRADED

        # Check for any degraded services
        has_degraded = any(
            status == ServiceStatus.DEGRADED
            for status in statuses_by_service.values()
        )
        if has_degraded:
            return SystemStatus.DEGRADED

        # All services are healthy or unknown
        return SystemStatus.HEALTHY


class SystemStatusAggregator:
    """Aggregates status from all service probes."""

    def __init__(self):
        self.logger = logging.getLogger("aggregator")
        self.probes = [
            DaemonProbe(),
            AgentsProbe(),
            IPCProbe(),
            OrchestratorProbe(),
            TimerProbe(),
            GatewayProbe(),
        ]

    async def gather_status(self) -> dict[str, Any]:
        """Execute all probes concurrently and aggregate results.

        Returns:
            dict with system_status, timestamp, response_time_ms, services
        """
        start_time = time.time()

        # Execute all probes concurrently with asyncio.gather
        try:
            probe_results = await asyncio.gather(
                *[probe.execute() for probe in self.probes],
                return_exceptions=True
            )

            # Convert exceptions to ProbeResult with UNKNOWN status
            processed_results = []
            for i, result in enumerate(probe_results):
                if isinstance(result, Exception):
                    probe_name = self.probes[i].service_name
                    self.logger.error(f"Probe {probe_name} raised exception: {result}")
                    processed_results.append(ProbeResult(
                        service_name=probe_name,
                        status=ServiceStatus.UNKNOWN,
                        data={},
                        error=str(result),
                        elapsed_ms=0.0
                    ))
                else:
                    processed_results.append(result)

            # Calculate system status
            system_status = StatusScorer.calculate_system_status(processed_results)

            # Build response
            elapsed_ms = (time.time() - start_time) * 1000.0

            services = {}
            for result in processed_results:
                service_data = {
                    "status": result.status.value,
                    **result.data
                }
                if result.error:
                    service_data["detail"] = result.error
                services[result.service_name] = service_data

            return {
                "system_status": system_status.value,
                "timestamp": datetime.now().isoformat(),
                "response_time_ms": round(elapsed_ms, 2),
                "services": services
            }

        except Exception as e:
            self.logger.error(f"Aggregator error: {e}")
            # Return critical status on aggregator failure
            elapsed_ms = (time.time() - start_time) * 1000.0
            return {
                "system_status": SystemStatus.CRITICAL.value,
                "timestamp": datetime.now().isoformat(),
                "response_time_ms": round(elapsed_ms, 2),
                "services": {},
                "error": str(e)
            }


def send_ipc_command(action: str, data: dict | None = None) -> dict:
    """Send command to brain daemon via Unix socket.

    Args:
        action: Action name (e.g., "agent_list", "ping")
        data: Optional action data

    Returns:
        Response dictionary
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(daemon_socket_path)

        # Build request (daemon expects: {"action": action, "data": data})
        request = {"action": action, "data": data or {}}
        request_json = json.dumps(request, ensure_ascii=False) + "\n"

        # Send request (newline-delimited, no length prefix)
        sock.sendall(request_json.encode("utf-8"))

        # Read response until newline
        response_bytes = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_bytes += chunk
            if b"\n" in response_bytes:
                break

        sock.close()

        if not response_bytes:
            return {"status": "error", "error": "Empty response from daemon"}

        return json.loads(response_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"IPC command failed: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/api/health")
async def get_health() -> dict[str, Any]:
    """Get system health status."""
    # Test daemon connection
    result = send_ipc_command("ping")

    if result.get("status") != "ok":
        return {
            "status": "degraded",
            "daemon": "disconnected",
            "timestamp": datetime.now().isoformat(),
            "error": result.get("error"),
        }

    return {
        "status": "ok",
        "daemon": "connected",
        "timestamp": datetime.now().isoformat(),
        "service": "monitor_service",
    }


@app.get("/api/agents")
async def get_agents(include_offline: bool = False) -> dict[str, Any]:
    """Get list of all agents with status.

    Args:
        include_offline: Include offline agents in the list (default: False)

    Returns:
        JSON with agents list
    """
    try:
        result = send_ipc_command("agent_list", {"include_offline": include_offline})

        if result.get("status") != "ok":
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to list agents"))

        agents = result.get("agents", [])
        instances = result.get("instances", [])

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "count": result.get("count", 0),
            "instance_count": result.get("instance_count", 0),
            "agents": agents,
            "instances": instances,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/stats")
async def get_agents_stats() -> dict[str, Any]:
    """Get agent statistics summary.

    Returns:
        JSON with agent statistics
    """
    try:
        # Get all agents (including offline)
        result = send_ipc_command("agent_list", {"include_offline": True})

        if result.get("status") != "ok":
            raise HTTPException(status_code=500, detail="Failed to list agents")

        agents = result.get("agents", [])
        instances = result.get("instances", [])

        # Calculate statistics
        total_agents = len(agents)
        online_agents = sum(1 for a in agents if a.get("online", False))
        offline_agents = total_agents - online_agents

        total_instances = len(instances)
        online_instances = sum(1 for i in instances if i.get("online", False))
        offline_instances = total_instances - online_instances

        # Categorize by type
        service_agents = []
        regular_agents = []

        for agent in agents:
            agent_name = agent.get("name", "")
            if agent_name.startswith("service"):
                service_agents.append(agent_name)
            else:
                regular_agents.append(agent_name)

        # Get idle time distribution
        idle_times = []
        for instance in instances:
            if instance.get("online", False):
                idle_seconds = instance.get("idle_seconds", 0)
                idle_times.append(idle_seconds)

        avg_idle = sum(idle_times) / len(idle_times) if idle_times else 0

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_agents": total_agents,
                "online_agents": online_agents,
                "offline_agents": offline_agents,
                "total_instances": total_instances,
                "online_instances": online_instances,
                "offline_instances": offline_instances,
            },
            "categories": {
                "service_agents": {
                    "count": len(service_agents),
                    "names": service_agents,
                },
                "regular_agents": {
                    "count": len(regular_agents),
                    "names": regular_agents,
                },
            },
            "performance": {
                "average_idle_seconds": round(avg_idle, 2),
            },
        }
    except Exception as e:
        logger.error(f"Error getting agent stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ipc/stats")
async def get_ipc_stats() -> dict[str, Any]:
    """Get IPC message queue statistics.

    Returns:
        JSON with IPC message statistics from reliability store
    """
    global ipc_state_store

    if ipc_state_store is None:
        raise HTTPException(
            status_code=503,
            detail="IPC state store not initialized"
        )

    try:
        # Get stats from MessageStateStore
        stats = ipc_state_store.get_stats()

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "ipc_reliability": {
                "total_messages": stats.get("total", 0),
                "pending": stats.get("pending", 0),
                "acked": stats.get("acked", 0),
                "failed": stats.get("failed", 0),
                "by_status": stats.get("by_status", {}),
            },
            "note": "Statistics from IPC reliability tracking (timer service)",
        }
    except Exception as e:
        logger.error(f"Error getting IPC stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/status")
async def get_system_status() -> dict[str, Any]:
    """Get unified system status across all services.

    Returns:
        JSON with system_status, timestamp, response_time_ms, and services details
    """
    try:
        aggregator = SystemStatusAggregator()
        result = await aggregator.gather_status()
        return result
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint with API documentation."""
    return {
        "service": "Brain System Monitor",
        "version": "1.0.0",
        "endpoints": {
            "/api/health": "System health status",
            "/api/system/status": "Unified system status across all services (BS-005)",
            "/api/agents": "List all agents (query: include_offline=true|false)",
            "/api/agents/stats": "Agent statistics summary",
            "/api/ipc/stats": "IPC message queue statistics",
            "/": "This documentation",
        },
        "example_usage": {
            "system_status": "GET /api/system/status",
            "list_online_agents": "GET /api/agents",
            "list_all_agents": "GET /api/agents?include_offline=true",
            "get_agent_stats": "GET /api/agents/stats",
            "get_ipc_stats": "GET /api/ipc/stats",
            "health_check": "GET /api/health",
        },
    }


def main() -> None:
    """Main entry point."""
    global daemon_socket_path, ipc_state_store

    parser = argparse.ArgumentParser(description="Brain System Monitor Service")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8100,
        help="Port to listen on (default: 8100)",
    )
    parser.add_argument(
        "--socket",
        default="/tmp/brain_ipc.sock",
        help="Brain daemon socket path",
    )
    parser.add_argument(
        "--ipc-state-db",
        default="/xkagent_infra/runtime/data/ipc_state.db",
        help="IPC state database path",
    )
    args = parser.parse_args()

    # Set daemon socket path
    daemon_socket_path = args.socket

    # Initialize IPC state store
    logger.info(f"Initializing IPC state store: {args.ipc_state_db}")
    try:
        ipc_state_store = MessageStateStore(db_path=args.ipc_state_db)
        logger.info("✅ IPC state store initialized")
    except Exception as e:
        logger.warning(f"⚠️ IPC state store initialization failed: {e}")
        logger.warning("IPC stats endpoint will be unavailable")

    # Test daemon connection
    logger.info(f"Testing daemon connection: {daemon_socket_path}")
    result = send_ipc_command("ping")
    if result.get("status") == "ok":
        logger.info("✅ Daemon connection successful")
    else:
        logger.warning(f"⚠️ Daemon connection failed: {result.get('error')}")

    # Start server
    logger.info(f"Starting Brain System Monitor on {args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
