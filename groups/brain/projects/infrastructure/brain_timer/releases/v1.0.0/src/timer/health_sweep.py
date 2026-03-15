"""Health sweep engine for IPC heartbeat monitoring."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from timer.alert_fallback import alert_fallback
from timer.daemon_client import IPCError


logger = logging.getLogger("service-timer.health-sweep")


class HealthSweep:
    """Execute periodic heartbeat scans and emit health events."""

    def __init__(self, daemon_client: Any, runbook_config: dict[str, Any], agent_name: str) -> None:
        self.daemon = daemon_client
        self.agent_name = agent_name
        self.alert_state: dict[str, dict[str, float]] = {}
        self.runbook = self._normalize_runbook(runbook_config)

    def update_runbook(self, runbook_config: dict[str, Any]) -> None:
        self.runbook = self._normalize_runbook(runbook_config)

    async def sweep(self) -> dict[str, list[str]]:
        """Run one heartbeat sweep."""
        try:
            result = await asyncio.to_thread(self.daemon.list_agents, include_offline=True)
        except IPCError:
            logger.error("Health sweep: daemon unreachable, skipping")
            return {"alerts": [], "recovered": []}

        agents = result.get("agents", []) if isinstance(result, dict) else []
        now = time.time()
        targets_config = self.runbook.get("targets", {})
        defaults = self.runbook.get("defaults", {})

        current_alerts: set[str] = set()
        new_alerts: list[str] = []

        for agent_info in agents:
            if not isinstance(agent_info, dict):
                continue

            name = str(agent_info.get("name", "")).strip()
            if not name:
                continue
            is_online = bool(agent_info.get("online", True))
            if (not is_online) and (name not in targets_config):
                continue

            idle_seconds = self._resolve_idle_seconds(agent_info, now)
            if idle_seconds is None:
                continue

            config = targets_config.get(name, defaults)
            threshold = float(config.get("threshold_seconds", 120) or 120)

            if idle_seconds > threshold:
                current_alerts.add(name)
                if name not in self.alert_state:
                    alert_target = self._resolve_alert_target(config)
                    self.alert_state[name] = {
                        "alerted_at": now,
                        "idle_at_alert": idle_seconds,
                        "alert_target": alert_target,
                    }
                    await self._send_health_alert(
                        name,
                        config,
                        idle_seconds,
                        threshold,
                        alert_target=alert_target,
                    )
                    new_alerts.append(name)

        recovered_names = sorted(set(self.alert_state.keys()) - current_alerts)
        for name in recovered_names:
            state = self.alert_state.pop(name)
            downtime = now - state["alerted_at"]
            alert_target = str(state.get("alert_target") or "").strip() or "service-agentctl"
            await self._send_health_recovered(name, downtime, alert_target=alert_target)

        return {"alerts": sorted(new_alerts), "recovered": recovered_names}

    def _normalize_runbook(self, runbook_config: dict[str, Any] | None) -> dict[str, Any]:
        config = runbook_config if isinstance(runbook_config, dict) else {}
        if "health_monitor" in config and isinstance(config["health_monitor"], dict):
            config = config["health_monitor"]
        targets = config.get("targets")
        defaults = config.get("defaults")
        return {
            "targets": targets if isinstance(targets, dict) else {},
            "defaults": defaults if isinstance(defaults, dict) else {"threshold_seconds": 120},
        }

    def _resolve_alert_target(self, config: dict[str, Any]) -> str:
        target = str(config.get("alert_target") or "").strip()
        if target:
            return target
        default_target = str(self.runbook.get("defaults", {}).get("alert_target") or "").strip()
        if default_target:
            return default_target
        return "service-agentctl"

    def _resolve_idle_seconds(self, agent_info: dict[str, Any], now: float) -> float | None:
        idle_raw = agent_info.get("idle_seconds")
        if idle_raw is not None:
            try:
                return float(idle_raw)
            except (TypeError, ValueError):
                return None

        last_hb = agent_info.get("last_heartbeat")
        try:
            last_hb_float = float(last_hb)
        except (TypeError, ValueError):
            return None
        if last_hb_float <= 0:
            return None
        return max(0.0, now - last_hb_float)

    async def _send_health_alert(
        self,
        target: str,
        config: dict[str, Any],
        idle_seconds: float,
        threshold: float,
        alert_target: str,
    ) -> None:
        payload = {
            "event_type": "HEALTH_ALERT",
            "target": target,
            "target_type": config.get("type", "unknown"),
            "idle_seconds": idle_seconds,
            "threshold": threshold,
            "timestamp": _utc_now_iso(),
            "recovery_enabled": config.get("recovery_enabled", False),
            "runbook_entry": config,
        }
        send_failed = False
        try:
            await asyncio.to_thread(
                self.daemon.send,
                from_agent=self.agent_name,
                to_agent=alert_target,
                payload=payload,
                message_type="request",
            )
        except IPCError:
            send_failed = True
            channels = config.get("on_failure", {}).get("alert_channels")
            await alert_fallback(
                daemon_client=self.daemon,
                alert_message=(
                    f"[HEALTH_ALERT] {target} heartbeat timeout {idle_seconds:.0f}s "
                    f"(threshold {threshold:.0f}s)"
                ),
                alert_level="critical",
                target=target,
                channels=channels if isinstance(channels, list) else None,
            )
        recovery_enabled = bool(config.get("recovery_enabled", False))
        if not recovery_enabled:
            return

        steps = config.get("recovery_steps", [])
        success = await self._execute_recovery(target, steps if isinstance(steps, list) else [])
        if success:
            state = self.alert_state.pop(target, None)
            downtime = 0.0
            if isinstance(state, dict):
                alerted_at = float(state.get("alerted_at", time.time()) or time.time())
                downtime = max(0.0, time.time() - alerted_at)
            logger.info("Recovery succeeded for %s", target)
            await self._send_health_recovered(target, downtime, alert_target=alert_target)
            return

        logger.error("Recovery failed for %s", target)
        if send_failed:
            return
        channels = config.get("on_failure", {}).get("alert_channels")
        message = config.get("on_failure", {}).get("message") or (
            f"{target} auto recovery failed, manual intervention required"
        )
        await alert_fallback(
            daemon_client=self.daemon,
            alert_message=message,
            alert_level="critical",
            target=target,
            channels=channels if isinstance(channels, list) else None,
        )

    async def _send_health_recovered(self, target: str, downtime: float, alert_target: str) -> None:
        payload = {
            "event_type": "HEALTH_RECOVERED",
            "target": target,
            "downtime_seconds": downtime,
            "timestamp": _utc_now_iso(),
        }
        try:
            await asyncio.to_thread(
                self.daemon.send,
                from_agent=self.agent_name,
                to_agent=alert_target,
                payload=payload,
                message_type="request",
            )
        except IPCError:
            logger.warning("Failed to send HEALTH_RECOVERED for %s", target)

    async def _execute_recovery(self, target: str, steps: list[dict[str, Any]]) -> bool:
        for step in steps:
            if not isinstance(step, dict):
                return False
            action = str(step.get("action", "")).strip()

            if action == "supervisorctl_restart":
                program = str(step.get("target") or target).strip()
                if not program:
                    return False
                ok = await asyncio.to_thread(
                    self._run_command,
                    ["supervisorctl", "restart", program],
                    15,
                )
                if not ok:
                    return False
            elif action == "agentctl_restart":
                agent = str(step.get("target") or target).strip()
                if not agent:
                    return False
                ok = await asyncio.to_thread(
                    self._run_command,
                    [
                        "/xkagent_infra/brain/infrastructure/service/agent-ctl/bin/agentctl",
                        "restart",
                        agent,
                        "--apply",
                    ],
                    30,
                )
                if not ok:
                    return False
            elif action == "verify":
                wait_seconds = float(step.get("wait_seconds", 0) or 0)
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                check = str(step.get("check", "")).strip()
                verify_target = str(step.get("target") or target).strip()
                if check == "ipc_online":
                    if not await self._is_target_online(verify_target):
                        return False
            else:
                logger.warning("Unknown recovery action: %s", action)
                return False
        return True

    def _run_command(self, cmd: list[str], timeout: int) -> bool:
        try:
            proc = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True, check=False)
        except Exception as exc:
            logger.error("Recovery command failed to start: %s (%s)", cmd, exc)
            return False
        if proc.returncode != 0:
            logger.error(
                "Recovery command failed: %s rc=%s stdout=%s stderr=%s",
                cmd,
                proc.returncode,
                (proc.stdout or "").strip(),
                (proc.stderr or "").strip(),
            )
            return False
        return True

    async def _is_target_online(self, target_name: str) -> bool:
        try:
            result = await asyncio.to_thread(self.daemon.list_agents, include_offline=True)
        except IPCError:
            return False
        if not isinstance(result, dict):
            return False
        agents = result.get("agents", [])
        if not isinstance(agents, list):
            return False
        for info in agents:
            if not isinstance(info, dict):
                continue
            if str(info.get("name", "")).strip() != target_name:
                continue
            return bool(info.get("online", False))
        return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
