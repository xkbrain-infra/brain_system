from __future__ import annotations

import importlib.util as _ilu
from typing import Any

from config.loader import DEFAULT_CONFIG_DIR, YAMLConfigLoader

# SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_DaemonClient = _mod.DaemonClient


class Notifier:
    """Notify manager (and eventually user) via IPC."""

    def __init__(self, *, from_agent: str, manager_agent: str = "manager", audit_logger: Any = None) -> None:
        self._from_agent = from_agent
        self._manager_agent = manager_agent
        self._audit = audit_logger
        self._config_loader = YAMLConfigLoader(config_dir=DEFAULT_CONFIG_DIR)
        self._last_sent: dict[str, float] = {}
        self._notification_queue: list[dict] = []
        self._ipc = _DaemonClient()

    def _daemon_request(self, action: str, data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._ipc._send_request(action, data)
        except Exception:
            return None

    def notify_manager(self, content: str, payload: dict[str, Any] | None = None) -> None:
        """Enhanced notification with batching and persistence."""
        body = {"content": content, "payload": payload or {}}
        if self._audit:
            self._audit.log_event("orchestrator_notify_manager", body)
            
        event_type = ""
        if payload and isinstance(payload, dict):
            event_type = str(payload.get("event_type") or "")
            
        # Implement notification batching to prevent storms
        now = __import__('time').time()
        notification_key = f"{event_type}:{content[:50]}"
        
        # Check cooldown
        last_sent = self._last_sent.get(notification_key, 0)
        if now - last_sent < 5.0:  # 5 second cooldown per notification type
            # Queue for batch sending instead of dropping
            self._notification_queue.append({
                "content": content,
                "payload": payload,
                "event_type": event_type,
            })
            return
            
        self._last_sent[notification_key] = now
        
        # Send notification
        self._daemon_request(
            "ipc_send",
            {
                "from": self._from_agent,
                "to": self._manager_agent,
                "payload": {"event_type": event_type or "orchestrator_alert", "content": content, **(payload or {})},
                "message_type": "request",
            },
        )
        
        # Process queued notifications if any
        self._process_notification_queue()

    def _process_notification_queue(self) -> None:
        """Process queued notifications for batch sending."""
        if not hasattr(self, '_notification_queue'):
            self._notification_queue = []
            
        if len(self._notification_queue) > 10:  # Batch size limit
            # Send batched notification
            batched_content = f"[{len(self._notification_queue)} queued notifications]"
            batched_payload = {
                "event_type": "batched_notifications",
                "queued_count": len(self._notification_queue),
                "queued_items": self._notification_queue[:10],  # Include first 10 items
            }
            
            self._daemon_request(
                "ipc_send",
                {
                    "from": self._from_agent,
                    "to": self._manager_agent,
                    "payload": batched_payload,
                    "message_type": "request",
                },
            )
            
            # Clear processed items
            self._notification_queue = self._notification_queue[10:]

    def __init__(self, *, from_agent: str, manager_agent: str = "manager", audit_logger: Any = None) -> None:
        self._from_agent = from_agent
        self._manager_agent = manager_agent
        self._audit = audit_logger
        self._config_loader = YAMLConfigLoader(config_dir=DEFAULT_CONFIG_DIR)
        self._last_sent: dict[str, float] = {}
        self._notification_queue: list[dict] = []
        self._ipc = _DaemonClient()

    def notify_telegram_admins(self, content: str, *, kind: str = "", agent: str = "") -> None:
        """Send alert to Telegram via webhook_gateway outbound agent, if configured.

        Uses whitelist.notifications.telegram.chat_ids.
        """
        try:
            cfg = self._config_loader.get_whitelist()
            root = cfg.get("whitelist", {}) if isinstance(cfg, dict) else {}
            notif = root.get("notifications", {}) if isinstance(root, dict) else {}
            if not (isinstance(notif, dict) and bool(notif.get("enabled", True))):
                return
            cooldown = int(notif.get("cooldown_seconds", 300) or 300)
            tg = notif.get("telegram", {}) if isinstance(notif, dict) else {}
            chat_ids = tg.get("chat_ids", []) if isinstance(tg, dict) else []
            if not isinstance(chat_ids, list):
                return

            key = f"{kind}:{agent}"
            now = __import__("time").time()
            last = self._last_sent.get(key, 0.0)
            if now - last < cooldown:
                return
            self._last_sent[key] = now

            for cid in chat_ids:
                chat_id = str(cid).strip()
                if not chat_id or "PLACEHOLDER" in chat_id:
                    continue
                self._daemon_request(
                    "ipc_send",
                    {
                        "from": self._from_agent,
                        "to": "telegram",
                        "payload": {
                            "chat_id": chat_id,
                            "content": content,
                            "parse_mode": None,
                        },
                        "message_type": "request",
                    },
                )
        except Exception:
            return
