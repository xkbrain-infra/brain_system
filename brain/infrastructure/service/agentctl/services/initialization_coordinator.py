#!/usr/bin/env python3
"""
InitializationCoordinator - 系统恢复协调器

负责 orchestrator 重启后的系统恢复流程：
1. 广播 RECOVERY_START 消息
2. 分级启动 agents (Level 0-3)
3. 收集 READY ACK 响应
4. 广播 SYSTEM_READY 最终状态
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from services.audit_logger import AuditLogger


class RecoveryStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class RecoveryConfig:
    """Recovery configuration."""
    levels: dict[int, list[str]] = field(default_factory=lambda: {
        0: ["service-agentctl", "service-brain_timer", "service-brain_task_manager"],
        1: ["agent-system_devops"],
        2: ["agent-brain_frontdesk"],
        3: ["*"],  # All remaining agents
    })
    level_timeout_s: int = 15  # Increased for C++ services (brain_task_manager needs ~12s)
    overall_timeout_s: int = 60
    lock_file: str = "/tmp/recovery.lock"
    heartbeat_interval_s: int = 5
    coordinator_timeout_s: int = 15


@dataclass
class AgentStatus:
    """Status of an individual agent during recovery."""
    name: str
    level: int
    status: str = "pending"  # pending, starting, ready, failed
    ready_at: float | None = None
    error: str | None = None


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    run_id: str
    status: RecoveryStatus
    total_agents: int
    ready_count: int
    failed_count: int
    skipped_count: int
    ready_agents: list[str]
    failed_agents: list[str]
    skipped_agents: list[str]
    duration_seconds: float
    levels_completed: list[int]


class InitializationCoordinator:
    """Coordinates system recovery after orchestrator restart."""

    def __init__(
        self,
        *,
        self_name: str,
        daemon_client: Any,
        launcher: Any,
        audit: AuditLogger | None = None,
        config: RecoveryConfig | None = None,
    ) -> None:
        self._self_name = self_name
        self._daemon = daemon_client
        self._launcher = launcher
        self._audit = audit
        self._config = config or RecoveryConfig()

        self._run_id: str = ""
        self._agent_statuses: dict[str, AgentStatus] = {}
        self._conversation_id: str = ""

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._audit:
            self._audit.log_event(event_type, payload)
        else:
            ts = datetime.now().isoformat(timespec="seconds")
            print(f"[{ts}] [{event_type}] {json.dumps(payload, ensure_ascii=False)}")

    def _acquire_coordinator_lock(self) -> bool:
        """Try to acquire coordinator lock (first-come-first-serve)."""
        lock_path = Path(self._config.lock_file)
        try:
            if lock_path.exists():
                # Check if lock is stale
                lock_data = json.loads(lock_path.read_text())
                lock_time = lock_data.get("timestamp", 0)
                if time.time() - lock_time < self._config.coordinator_timeout_s:
                    # Another coordinator is active
                    return False

            # Acquire lock
            lock_data = {
                "coordinator": self._self_name,
                "run_id": self._run_id,
                "timestamp": time.time(),
            }
            lock_path.write_text(json.dumps(lock_data))
            return True
        except Exception as e:
            self._log_event("coordinator_lock_error", {"error": str(e)})
            return False

    def _release_coordinator_lock(self) -> None:
        """Release coordinator lock."""
        try:
            lock_path = Path(self._config.lock_file)
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass

    def _update_heartbeat(self) -> None:
        """Update lock file timestamp (heartbeat)."""
        try:
            lock_path = Path(self._config.lock_file)
            if lock_path.exists():
                lock_data = json.loads(lock_path.read_text())
                lock_data["timestamp"] = time.time()
                lock_path.write_text(json.dumps(lock_data))
        except Exception:
            pass

    def _get_agents_for_level(self, level: int) -> list[str]:
        """Get agent names for a specific level."""
        level_agents = self._config.levels.get(level, [])

        if "*" in level_agents:
            # Level contains wildcard - get all remaining agents
            all_agents = set(self._launcher.get_agent_spec().keys())
            assigned = set()
            for lvl, agents in self._config.levels.items():
                if "*" not in agents:
                    assigned.update(agents)
            return sorted(all_agents - assigned)

        return level_agents

    def _build_recovery_start_payload(self) -> dict[str, Any]:
        """Build RECOVERY_START message payload."""
        return {
            "event_type": "RECOVERY_START",
            "run_id": self._run_id,
            "coordinator": self._self_name,
            "timestamp": time.time(),
            "levels": self._config.levels,
            "policy": {
                "level_timeout_s": self._config.level_timeout_s,
                "overall_timeout_s": self._config.overall_timeout_s,
            },
        }

    def _build_system_ready_payload(self, result: RecoveryResult) -> dict[str, Any]:
        """Build SYSTEM_READY message payload."""
        return {
            "event_type": "SYSTEM_READY",
            "run_id": self._run_id,
            "coordinator": self._self_name,
            "timestamp": time.time(),
            "status": result.status.value,
            "stats": {
                "total": result.total_agents,
                "ready": result.ready_count,
                "failed": result.failed_count,
                "skipped": result.skipped_count,
                "duration_s": result.duration_seconds,
            },
            "ready_agents": result.ready_agents,
            "failed_agents": result.failed_agents,
        }

    async def _broadcast_to_agents(
        self,
        agents: list[str],
        payload: dict[str, Any],
    ) -> int:
        """Broadcast message to multiple agents."""
        sent_count = 0
        for agent in agents:
            if agent == self._self_name:
                continue
            try:
                self._daemon.send(
                    from_agent=self._self_name,
                    to_agent=agent,
                    payload=payload,
                    message_type="request",
                    conversation_id=self._conversation_id,
                )
                sent_count += 1
            except Exception as e:
                self._log_event("broadcast_error", {"agent": agent, "error": str(e)})
        return sent_count

    async def _wait_for_ready_acks(
        self,
        agents: list[str],
        timeout_s: int,
    ) -> tuple[list[str], list[str]]:
        """Wait for agents to become online (via heartbeat detection).

        Uses daemon's agent_list to check if agents are online,
        rather than requiring explicit READY_ACK messages.
        """
        ready: list[str] = []
        pending = set(agents)
        pending.discard(self._self_name)

        deadline = time.time() + timeout_s

        while pending and time.time() < deadline:
            try:
                # Check which agents are online via daemon
                resp = self._daemon.list_agents(include_offline=False)
                if resp and resp.get("status") == "ok":
                    instances = resp.get("instances", []) or []
                    online_agents = set()
                    for inst in instances:
                        if isinstance(inst, dict) and inst.get("online"):
                            agent_name = str(inst.get("agent_name") or "")
                            if agent_name:
                                online_agents.add(agent_name)

                    # Check pending agents
                    newly_ready = []
                    for agent in list(pending):
                        if agent in online_agents:
                            pending.discard(agent)
                            ready.append(agent)
                            newly_ready.append(agent)
                            if agent in self._agent_statuses:
                                self._agent_statuses[agent].status = "ready"
                                self._agent_statuses[agent].ready_at = time.time()

                    if newly_ready:
                        self._log_event("agents_ready", {"agents": newly_ready, "run_id": self._run_id})

            except Exception as e:
                self._log_event("wait_ready_error", {"error": str(e)})

            # Update heartbeat
            self._update_heartbeat()

            await asyncio.sleep(1.0)

        failed = list(pending)
        return ready, failed

    def _parse_agent_name(self, instance_id: str) -> str:
        """Extract agent name from instance_id (e.g., 'agent@session:id' -> 'agent')."""
        return (instance_id or "").split("@")[0].strip()

    async def _start_level(self, level: int) -> tuple[list[str], list[str]]:
        """Start agents at a specific level and wait for them to be ready."""
        agents = self._get_agents_for_level(level)
        if not agents:
            return [], []

        self._log_event("level_start", {"level": level, "agents": agents})

        # Initialize agent statuses
        for agent in agents:
            self._agent_statuses[agent] = AgentStatus(name=agent, level=level, status="starting")

        # Ensure agents are running (use launcher)
        for agent in agents:
            if agent == self._self_name:
                continue
            try:
                # Check if agent needs to be started
                spec = self._launcher.get_agent_spec()
                if agent in spec:
                    result = self._launcher.restart(agent, reason=f"recovery_level_{level}")
                    if not result.success:
                        self._agent_statuses[agent].status = "failed"
                        self._agent_statuses[agent].error = result.error or "start failed"
            except Exception as e:
                self._agent_statuses[agent].status = "failed"
                self._agent_statuses[agent].error = str(e)

        # Wait a bit for agents to initialize
        await asyncio.sleep(2)

        # Send RECOVERY_START to this level's agents
        payload = self._build_recovery_start_payload()
        payload["current_level"] = level
        await self._broadcast_to_agents(agents, payload)

        # Wait for READY ACKs
        ready, failed = await self._wait_for_ready_acks(agents, self._config.level_timeout_s)

        self._log_event("level_complete", {
            "level": level,
            "ready": ready,
            "failed": failed,
        })

        return ready, failed

    async def coordinate_recovery(self) -> RecoveryResult:
        """Main recovery coordination flow."""
        start_time = time.time()
        self._run_id = uuid.uuid4().hex[:12]
        self._conversation_id = f"recovery_{self._run_id}"
        self._agent_statuses.clear()

        self._log_event("recovery_start", {
            "run_id": self._run_id,
            "coordinator": self._self_name,
            "config": {
                "levels": self._config.levels,
                "level_timeout_s": self._config.level_timeout_s,
                "overall_timeout_s": self._config.overall_timeout_s,
            },
        })

        # Try to acquire coordinator lock
        if not self._acquire_coordinator_lock():
            self._log_event("recovery_skipped", {"reason": "another_coordinator_active"})
            return RecoveryResult(
                run_id=self._run_id,
                status=RecoveryStatus.FAILED,
                total_agents=0,
                ready_count=0,
                failed_count=0,
                skipped_count=0,
                ready_agents=[],
                failed_agents=[],
                skipped_agents=[],
                duration_seconds=0,
                levels_completed=[],
            )

        try:
            all_ready: list[str] = []
            all_failed: list[str] = []
            levels_completed: list[int] = []

            # Process each level in order
            max_level = max(self._config.levels.keys())
            for level in range(max_level + 1):
                if level not in self._config.levels:
                    continue

                # Check overall timeout
                if time.time() - start_time > self._config.overall_timeout_s:
                    self._log_event("recovery_timeout", {"at_level": level})
                    break

                ready, failed = await self._start_level(level)
                all_ready.extend(ready)
                all_failed.extend(failed)
                levels_completed.append(level)

            # Determine final status
            total = len(all_ready) + len(all_failed)
            if len(all_failed) == 0:
                status = RecoveryStatus.COMPLETED
            elif len(all_ready) > 0:
                status = RecoveryStatus.PARTIAL
            else:
                status = RecoveryStatus.FAILED

            duration = time.time() - start_time

            result = RecoveryResult(
                run_id=self._run_id,
                status=status,
                total_agents=total,
                ready_count=len(all_ready),
                failed_count=len(all_failed),
                skipped_count=0,
                ready_agents=all_ready,
                failed_agents=all_failed,
                skipped_agents=[],
                duration_seconds=round(duration, 2),
                levels_completed=levels_completed,
            )

            # Broadcast SYSTEM_READY
            all_agents = list(self._launcher.get_agent_spec().keys())
            await self._broadcast_to_agents(all_agents, self._build_system_ready_payload(result))

            self._log_event("recovery_complete", {
                "run_id": self._run_id,
                "status": status.value,
                "ready": len(all_ready),
                "failed": len(all_failed),
                "duration_s": result.duration_seconds,
            })

            return result

        finally:
            self._release_coordinator_lock()
