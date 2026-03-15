"""Alert Manager for Agent Dashboard."""

import importlib.util as _ilu
import time
import logging
from typing import Any

# SSOT: /brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_DaemonClient = _mod.DaemonClient

logger = logging.getLogger("agent_dashboard.alerter")


class Alerter:
    """Manages alerts with deduplication and cooldown."""

    def __init__(
        self,
        storage,
        daemon_socket: str,
        target_agent: str = "telegram",
        cooldown_seconds: int = 300,
        enabled: bool = True,
    ) -> None:
        self.storage = storage
        self.daemon_socket = daemon_socket
        self.target_agent = target_agent
        self.cooldown_seconds = cooldown_seconds
        self.enabled = enabled
        self._ipc = _DaemonClient(socket_path=daemon_socket)

    def _send_ipc(self, to: str, message: str) -> bool:
        """Send message via IPC."""
        try:
            resp = self._ipc.send(
                from_agent="service-dashboard",
                to_agent=to,
                payload={"content": message},
                message_type="request",
            )
            return resp.get("status") == "ok"
        except Exception as e:
            logger.error(f"Failed to send IPC message: {e}")
            return False

    def check_and_alert(
        self,
        agent: dict[str, Any],
        prev_state: dict[str, Any] | None,
    ) -> None:
        """Check state change and send alert if needed."""
        if not self.enabled:
            return

        agent_name = agent.get("name", "unknown")
        instance_id = agent.get("instance_id", "")
        online = agent.get("online", False)
        now = int(time.time())

        # Detect state change
        if prev_state is not None:
            was_online = prev_state.get("online", False)

            if was_online and not online:
                # Agent went offline
                self._send_alert(
                    agent_name=agent_name,
                    instance_id=instance_id,
                    alert_type="offline",
                    message=f"🔴 Agent 离线: {instance_id or agent_name}",
                    now=now,
                )
            elif not was_online and online:
                # Agent came back online
                self._send_alert(
                    agent_name=agent_name,
                    instance_id=instance_id,
                    alert_type="online",
                    message=f"🟢 Agent 恢复在线: {instance_id or agent_name}",
                    now=now,
                )

    def _send_alert(
        self,
        agent_name: str,
        instance_id: str,
        alert_type: str,
        message: str,
        now: int,
    ) -> None:
        """Send alert with cooldown check."""
        # Check cooldown
        cooldown_until = self.storage.get_active_cooldown(agent_name, alert_type)
        if cooldown_until and cooldown_until > now:
            logger.debug(f"Alert suppressed (cooldown): {agent_name}/{alert_type}")
            return

        # Save alert
        new_cooldown = now + self.cooldown_seconds
        alert_id = self.storage.save_alert(
            agent_name=agent_name,
            instance_id=instance_id,
            alert_type=alert_type,
            message=message,
            cooldown_until=new_cooldown,
        )

        # Send via IPC
        success = self._send_ipc(self.target_agent, message)
        if success:
            self.storage.mark_alert_sent(alert_id)
            logger.info(f"Alert sent: {message}")
        else:
            logger.error(f"Failed to send alert: {message}")

    def send_test_alert(self, message: str) -> bool:
        """Send a test alert message."""
        return self._send_ipc(self.target_agent, f"🧪 测试告警: {message}")

    def send_startup_notification(self) -> bool:
        """Send startup notification (also registers via heartbeat)."""
        return self._send_ipc(self.target_agent, "📊 Agent Dashboard 服务已启动")

    def check_context_alert(
        self,
        session_id: str,
        usage_percent: float,
        threshold: float = 80.0,
    ) -> None:
        """Check context usage and send alert if over threshold."""
        if not self.enabled:
            return

        if usage_percent < threshold:
            return

        now = int(time.time())
        alert_type = "context_high"

        # Check cooldown
        cooldown_until = self.storage.get_active_cooldown(session_id, alert_type)
        if cooldown_until and cooldown_until > now:
            logger.debug(f"Context alert suppressed (cooldown): {session_id}")
            return

        # Send alert
        message = f"⚠️ Context 使用率过高: {session_id[:8]}... ({usage_percent:.1f}%)"

        new_cooldown = now + self.cooldown_seconds
        alert_id = self.storage.save_alert(
            agent_name=session_id,
            instance_id=session_id,
            alert_type=alert_type,
            message=message,
            cooldown_until=new_cooldown,
        )

        success = self._send_ipc(self.target_agent, message)
        if success:
            self.storage.mark_alert_sent(alert_id)
            logger.info(f"Context alert sent: {message}")
        else:
            logger.error(f"Failed to send context alert: {message}")
