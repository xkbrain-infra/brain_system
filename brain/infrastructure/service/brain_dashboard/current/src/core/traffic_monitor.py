"""Traffic Monitor for Agent Dashboard.

Monitors IPC message flow, API request metrics, and system resource usage.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agent_dashboard.traffic")


@dataclass
class IPCMetrics:
    """IPC message metrics."""
    total_sent: int = 0
    total_received: int = 0
    messages_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bytes_transferred: int = 0
    errors: int = 0


@dataclass
class APIMetrics:
    """API request metrics."""
    total_requests: int = 0
    requests_by_endpoint: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    response_times: list[float] = field(default_factory=list)
    errors: int = 0
    error_rate: float = 0.0


@dataclass
class SystemMetrics:
    """System resource metrics."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    disk_percent: float = 0.0


@dataclass
class TrafficSnapshot:
    """Complete traffic snapshot at a point in time."""
    timestamp: int
    ipc: IPCMetrics
    api: APIMetrics
    system: SystemMetrics


class TrafficMonitor:
    """Monitor traffic metrics for dashboard."""

    def __init__(self, storage=None, max_history: int = 1000):
        self.storage = storage
        self.max_history = max_history
        self._snapshots: list[TrafficSnapshot] = []
        self._current_ipc = IPCMetrics()
        self._current_api = APIMetrics()
        self._running = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start traffic monitoring."""
        self._running = True
        logger.info("Traffic monitor started")

    async def stop(self) -> None:
        """Stop traffic monitoring."""
        self._running = False
        logger.info("Traffic monitor stopped")

    async def record_ipc_message(
        self,
        direction: str,  # 'sent' or 'received'
        msg_type: str,
        size_bytes: int = 0,
        error: bool = False
    ) -> None:
        """Record an IPC message."""
        async with self._lock:
            if direction == 'sent':
                self._current_ipc.total_sent += 1
            else:
                self._current_ipc.total_received += 1

            self._current_ipc.messages_by_type[msg_type] += 1
            self._current_ipc.bytes_transferred += size_bytes

            if error:
                self._current_ipc.errors += 1

    async def record_api_request(
        self,
        endpoint: str,
        response_time_ms: float,
        error: bool = False
    ) -> None:
        """Record an API request."""
        async with self._lock:
            self._current_api.total_requests += 1
            self._current_api.requests_by_endpoint[endpoint] += 1
            self._current_api.response_times.append(response_time_ms)

            # Keep only last 100 response times
            if len(self._current_api.response_times) > 100:
                self._current_api.response_times = self._current_api.response_times[-100:]

            if error:
                self._current_api.errors += 1

            # Calculate error rate
            if self._current_api.total_requests > 0:
                self._current_api.error_rate = (
                    self._current_api.errors / self._current_api.total_requests * 100
                )

    async def collect_system_metrics(self) -> SystemMetrics:
        """Collect system resource metrics."""
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / 1024 / 1024,
                memory_total_mb=memory.total / 1024 / 1024,
                disk_percent=disk.percent,
            )
        except ImportError:
            logger.debug("psutil not available, skipping system metrics")
            return SystemMetrics()
        except Exception as e:
            logger.warning(f"Failed to collect system metrics: {e}")
            return SystemMetrics()

    async def take_snapshot(self) -> TrafficSnapshot:
        """Take a snapshot of current traffic metrics."""
        async with self._lock:
            system = await self.collect_system_metrics()

            snapshot = TrafficSnapshot(
                timestamp=int(time.time()),
                ipc=IPCMetrics(
                    total_sent=self._current_ipc.total_sent,
                    total_received=self._current_ipc.total_received,
                    messages_by_type=dict(self._current_ipc.messages_by_type),
                    bytes_transferred=self._current_ipc.bytes_transferred,
                    errors=self._current_ipc.errors,
                ),
                api=APIMetrics(
                    total_requests=self._current_api.total_requests,
                    requests_by_endpoint=dict(self._current_api.requests_by_endpoint),
                    response_times=list(self._current_api.response_times),
                    errors=self._current_api.errors,
                    error_rate=self._current_api.error_rate,
                ),
                system=system,
            )

            self._snapshots.append(snapshot)

            # Keep only max_history snapshots
            if len(self._snapshots) > self.max_history:
                self._snapshots = self._snapshots[-self.max_history:]

            # Save to storage if available
            if self.storage:
                await self._save_to_storage(snapshot)

            return snapshot

    async def _save_to_storage(self, snapshot: TrafficSnapshot) -> None:
        """Save snapshot to storage."""
        try:
            self.storage.save_traffic_snapshot({
                "timestamp": snapshot.timestamp,
                "ipc_total_sent": snapshot.ipc.total_sent,
                "ipc_total_received": snapshot.ipc.total_received,
                "ipc_bytes": snapshot.ipc.bytes_transferred,
                "ipc_errors": snapshot.ipc.errors,
                "api_total_requests": snapshot.api.total_requests,
                "api_errors": snapshot.api.errors,
                "api_error_rate": snapshot.api.error_rate,
                "cpu_percent": snapshot.system.cpu_percent,
                "memory_percent": snapshot.system.memory_percent,
            })
        except Exception as e:
            logger.warning(f"Failed to save traffic snapshot: {e}")

    async def get_current_stats(self) -> dict[str, Any]:
        """Get current traffic statistics."""
        async with self._lock:
            avg_response_time = 0.0
            if self._current_api.response_times:
                avg_response_time = sum(self._current_api.response_times) / len(self._current_api.response_times)

            return {
                "ipc": {
                    "total_sent": self._current_ipc.total_sent,
                    "total_received": self._current_ipc.total_received,
                    "total_messages": self._current_ipc.total_sent + self._current_ipc.total_received,
                    "bytes_transferred": self._current_ipc.bytes_transferred,
                    "errors": self._current_ipc.errors,
                    "messages_by_type": dict(self._current_ipc.messages_by_type),
                },
                "api": {
                    "total_requests": self._current_api.total_requests,
                    "requests_by_endpoint": dict(self._current_api.requests_by_endpoint),
                    "avg_response_time_ms": round(avg_response_time, 2),
                    "errors": self._current_api.errors,
                    "error_rate": round(self._current_api.error_rate, 2),
                },
                "system": {
                    "cpu_percent": self._snapshots[-1].system.cpu_percent if self._snapshots else 0,
                    "memory_percent": self._snapshots[-1].system.memory_percent if self._snapshots else 0,
                } if self._snapshots else {},
            }

    async def get_history(self, minutes: int = 60) -> list[dict[str, Any]]:
        """Get traffic history for the past N minutes."""
        cutoff = int(time.time()) - (minutes * 60)
        history = []

        async with self._lock:
            for snapshot in self._snapshots:
                if snapshot.timestamp >= cutoff:
                    history.append({
                        "timestamp": snapshot.timestamp,
                        "ipc": {
                            "total_sent": snapshot.ipc.total_sent,
                            "total_received": snapshot.ipc.total_received,
                            "errors": snapshot.ipc.errors,
                        },
                        "api": {
                            "total_requests": snapshot.api.total_requests,
                            "errors": snapshot.api.errors,
                            "error_rate": snapshot.api.error_rate,
                        },
                        "system": {
                            "cpu_percent": snapshot.system.cpu_percent,
                            "memory_percent": snapshot.system.memory_percent,
                        },
                    })

        return history

    async def get_top_endpoints(self, limit: int = 5) -> list[tuple[str, int]]:
        """Get top N endpoints by request count."""
        async with self._lock:
            sorted_endpoints = sorted(
                self._current_api.requests_by_endpoint.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_endpoints[:limit]

    async def get_message_type_distribution(self) -> dict[str, int]:
        """Get IPC message type distribution."""
        async with self._lock:
            return dict(self._current_ipc.messages_by_type)


# Global traffic monitor instance
_traffic_monitor: TrafficMonitor | None = None


def get_traffic_monitor(storage=None) -> TrafficMonitor:
    """Get or create global traffic monitor instance."""
    global _traffic_monitor
    if _traffic_monitor is None:
        _traffic_monitor = TrafficMonitor(storage=storage)
    return _traffic_monitor
