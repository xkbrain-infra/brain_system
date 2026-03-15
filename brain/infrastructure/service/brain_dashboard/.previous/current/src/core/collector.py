"""Metrics Collector for Agent Dashboard."""

import time
import asyncio
import logging
from typing import Any, Callable

# SSOT: /brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DaemonClient = _mod.DaemonClient

logger = logging.getLogger("agent_dashboard.collector")


class Collector:
    """Collects agent metrics from IPC daemon with tiered intervals."""

    def __init__(
        self,
        daemon_socket: str,
        intervals: dict[str, int] | None = None,
        on_agent_collected: Callable[[dict, str], None] | None = None,
    ) -> None:
        """
        Initialize collector with tiered intervals.

        Args:
            daemon_socket: Path to daemon socket
            intervals: Dict of source_type -> interval_seconds
                       e.g. {"heartbeat": 10, "tmux_discovery": 30, "default": 30}
            on_agent_collected: Callback(agent_data, source_type) for each collected agent
        """
        self.client = DaemonClient(daemon_socket)
        self.intervals = intervals or {
            "heartbeat": 10,
            "tmux_discovery": 30,
            "register": 60,
            "default": 30,
        }
        self.on_agent_collected = on_agent_collected

        self._running = False
        self._task: asyncio.Task | None = None
        self._last_agents: list[dict] = []

        # Track last collection time per agent instance
        self._agent_last_collect: dict[str, float] = {}
        # Cache agent source types
        self._agent_sources: dict[str, str] = {}

        # Check interval is the minimum of all intervals
        self._check_interval = min(self.intervals.values())

    @property
    def last_agents(self) -> list[dict]:
        """Get last collected agents."""
        return self._last_agents

    def _get_interval_for_source(self, source: str) -> int:
        """Get collection interval for a source type."""
        return self.intervals.get(source, self.intervals.get("default", 30))

    def _should_collect(self, instance_id: str, source: str, now: float) -> bool:
        """Check if agent should be collected based on its interval."""
        last_collect = self._agent_last_collect.get(instance_id, 0)
        interval = self._get_interval_for_source(source)
        return (now - last_collect) >= interval

    def collect_all(self) -> list[dict[str, Any]]:
        """Fetch all agents from daemon (used for discovery)."""
        try:
            response = self.client.list_agents(include_offline=True)
            if response.get("status") == "ok":
                # Use instances array which has source field
                instances = response.get("instances", [])
                self._last_agents = instances

                # Update source cache
                for inst in instances:
                    instance_id = inst.get("instance_id", "")
                    source = inst.get("source", "unknown")
                    if instance_id:
                        self._agent_sources[instance_id] = source

                return instances
            else:
                logger.error(f"Daemon error: {response}")
                return []
        except Exception as e:
            logger.error(f"Collection failed: {e}")
            return []

    def collect_due_agents(self) -> list[dict[str, Any]]:
        """Collect agents that are due for collection based on their intervals."""
        now = time.time()

        # First fetch all agents to get current state
        all_agents = self.collect_all()
        if not all_agents:
            return []

        collected = []
        for agent in all_agents:
            instance_id = agent.get("instance_id", "")
            source = agent.get("source", "unknown")

            if not instance_id:
                continue

            if self._should_collect(instance_id, source, now):
                self._agent_last_collect[instance_id] = now
                collected.append(agent)

                if self.on_agent_collected:
                    self.on_agent_collected(agent, source)

        return collected

    async def _collect_loop(self) -> None:
        """Main collection loop with tiered intervals."""
        logger.info(f"Collector started, intervals={self.intervals}, check_interval={self._check_interval}s")

        while self._running:
            try:
                collected = await asyncio.get_event_loop().run_in_executor(
                    None, self.collect_due_agents
                )
                if collected:
                    # Group by source for logging
                    by_source: dict[str, int] = {}
                    for agent in collected:
                        src = agent.get("source", "unknown")
                        by_source[src] = by_source.get(src, 0) + 1

                    parts = [f"{src}:{cnt}" for src, cnt in by_source.items()]
                    logger.debug(f"Collected {len(collected)} agents: {', '.join(parts)}")

            except Exception as e:
                logger.error(f"Collection error: {e}")

            await asyncio.sleep(self._check_interval)

    async def start(self) -> None:
        """Start collector."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())

    async def stop(self) -> None:
        """Stop collector."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Collector stopped")

    def is_daemon_alive(self) -> bool:
        """Check if daemon is alive."""
        return self.client.ping()

    def get_agent_source(self, instance_id: str) -> str:
        """Get cached source type for an agent."""
        return self._agent_sources.get(instance_id, "unknown")
