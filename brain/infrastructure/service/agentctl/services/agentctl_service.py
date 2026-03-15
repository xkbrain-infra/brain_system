from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add parent directory to path for absolute imports
SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config.loader import DEFAULT_CONFIG_DIR, YAMLConfigLoader
from config.validator import validate_agents_registry
from core.dispatcher import BrainDaemonClient, Dispatcher

# NotifyClient for push-based IPC
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
from ipc_client import NotifyClient
from core.router import RouteDecision, Router
from handlers.command_handler import CommandHandler
from services.audit_logger import AuditLogger
from services.health import HealthMonitor
from services.initialization_coordinator import InitializationCoordinator, RecoveryConfig
from services.launcher import Launcher
from services.provisioner import Provisioner
from services.target_resolver import TargetResolver


@dataclass(frozen=True)
class InboundEvent:
    msg_id: str
    from_agent: str
    payload: dict[str, Any]


def _is_command(text: str) -> bool:
    return text.strip().startswith("/")


def _split_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    return parts[0], parts[1:]


def _default_task_id(payload: dict[str, Any]) -> str:
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat_id") or "")
    message_id = str(payload.get("message_id") or "")
    if platform and chat_id and message_id:
        return f"{platform}:{chat_id}:{message_id}"
    return uuid.uuid4().hex


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        return [text]
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        start = end
    return chunks


class AgentCtlService:
    """Merged service: Telegram entrypoint + routing + lifecycle orchestration + provision."""

    def __init__(
        self,
        *,
        agent_name: str,
        daemon: BrainDaemonClient,
        config_loader: YAMLConfigLoader,
        audit: AuditLogger,
        poll_interval_s: float = 0.2,
        outbound_agent: str = "telegram",
        telegram_max_chars: int = 3500,
        orchestrator_interval_s: int = 10,
        cleanup_before_start: bool = True,
        cleanup_timeout_seconds: int = 5,
        cleanup_skip_attached: bool = True,
    ) -> None:
        self._agent_name = agent_name
        self._daemon = daemon
        self._config = config_loader
        self._audit = audit
        self._poll_interval_s = poll_interval_s
        self._outbound_agent = outbound_agent
        self._telegram_max_chars = telegram_max_chars

        self._router = Router(config_loader)
        resolver = TargetResolver(daemon=daemon, config_loader=config_loader)
        self._dispatcher = Dispatcher(
            daemon=daemon,
            audit=audit,
            manager_agent_name=agent_name,
            target_resolver=resolver,
            config_loader=config_loader,
        )
        self._commands = CommandHandler(
            audit_logger=audit,
            supervisor=None,
            config_loader=config_loader,
            self_agent_name=agent_name,
        )

        self._launcher = Launcher(
            self_name=agent_name,
            check_interval_s=orchestrator_interval_s,
            audit_logger=audit,
            cleanup_before_start=cleanup_before_start,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
            cleanup_skip_attached=cleanup_skip_attached,
        )
        self._cleanup_before_start = cleanup_before_start
        self._coordinator = InitializationCoordinator(
            self_name=agent_name,
            daemon_client=daemon,
            launcher=self._launcher,
            audit=audit,
        )
        self._health = HealthMonitor()
        self._provisioner = Provisioner(audit_logger=audit, config_loader=config_loader, launcher=self._launcher)

        self._seen_task_ids: dict[str, float] = {}
        self._seen_ttl_s = 3600.0

        self._allowed_control_senders = self._load_allowed_control_senders()
        self._orchestrator_interval_s = orchestrator_interval_s
        self._last_orchestrator_tick = 0.0
        self._last_config_error_sig: str | None = None

    def _load_allowed_control_senders(self) -> set[str]:
        try:
            cfg = self._config.get_whitelist()
            root = cfg.get("whitelist", {}) if isinstance(cfg, dict) else {}
            ipc = root.get("ipc_control", {}) if isinstance(root, dict) else {}
            allowed = ipc.get("allowed_from_agents", []) if isinstance(ipc, dict) else []
            if isinstance(allowed, list):
                out = {str(x).strip() for x in allowed if str(x).strip()}
                out.add(self._agent_name)
                return out
        except Exception:
            pass
        return {self._agent_name}

    def _gc_seen(self) -> None:
        now = time.time()
        expired = [k for k, ts in self._seen_task_ids.items() if now - ts > self._seen_ttl_s]
        for k in expired:
            self._seen_task_ids.pop(k, None)

    def _mark_seen(self, task_id: str) -> bool:
        self._gc_seen()
        if task_id in self._seen_task_ids:
            return False
        self._seen_task_ids[task_id] = time.time()
        return True

    def _send_user_reply(self, payload: dict[str, Any], content: str) -> None:
        user_id = str(payload.get("user_id") or "")
        chat_id = str(payload.get("chat_id") or "")
        parse_mode = payload.get("parse_mode")

        chunks = _chunk_text(content, self._telegram_max_chars)
        for idx, chunk in enumerate(chunks, start=1):
            prefix = ""
            if len(chunks) > 1:
                prefix = f"({idx}/{len(chunks)}) "
            self._daemon.send(
                from_agent=self._agent_name,
                to_agent=self._outbound_agent,
                payload={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "content": prefix + chunk,
                    "parse_mode": parse_mode,
                },
                message_type="response",
            )

    def _notify_admins(self, content: str, *, kind: str = "", agent: str = "") -> None:
        try:
            cfg = self._config.get_whitelist()
            root = cfg.get("whitelist", {}) if isinstance(cfg, dict) else {}
            notif = root.get("notifications", {}) if isinstance(root, dict) else {}
            if not (isinstance(notif, dict) and bool(notif.get("enabled", True))):
                return
            tg = notif.get("telegram", {}) if isinstance(notif, dict) else {}
            chat_ids = tg.get("chat_ids", []) if isinstance(tg, dict) else []
            if not isinstance(chat_ids, list):
                return
            for cid in chat_ids:
                chat_id = str(cid).strip()
                if not chat_id or "PLACEHOLDER" in chat_id:
                    continue
                self._daemon.send(
                    from_agent=self._agent_name,
                    to_agent=self._outbound_agent,
                    payload={"user_id": "", "chat_id": chat_id, "content": content, "parse_mode": None},
                    message_type="request",
                )
        except Exception:
            return

    def _parse_agent_name(self, instance_id_or_name: str) -> str:
        s = (instance_id_or_name or "").strip()
        return s.split("@", 1)[0] if s else ""

    def _get_group_meta(self) -> dict[str, dict]:
        """Load group_meta from agents_registry."""
        cfg = self._config.get_agents_registry()
        return cfg.get("group_meta", {}) if isinstance(cfg, dict) else {}

    def _get_group_agents(self, group_name: str) -> list[str]:
        """Return agent names belonging to a group."""
        cfg = self._config.get_agents_registry()
        if not isinstance(cfg, dict):
            return []
        groups = cfg.get("groups", {})
        if not isinstance(groups, dict):
            return []
        agents = groups.get(group_name, [])
        if not isinstance(agents, list):
            return []
        return [str(a.get("name") or "").strip() for a in agents if isinstance(a, dict) and a.get("name")]

    def _wake_group(self, group_name: str, reason: str = "wake_on_demand") -> None:
        """Wake all stopped agents in a group (respects wake_policy)."""
        meta = self._get_group_meta().get(group_name)
        if not meta:
            raise ValueError(f"unknown group: {group_name}")

        policy = str(meta.get("wake_policy") or "manual").strip()
        if policy == "manual":
            raise ValueError(f"group '{group_name}' has wake_policy=manual, cannot wake via IPC")

        agent_names = self._get_group_agents(group_name)
        if not agent_names:
            self._audit.log_event("wake_group_empty", {"group": group_name})
            return

        # Role priority for startup order
        role_order = {"pmo": 0, "architect": 1, "devops": 2}
        spec_map = self._launcher.get_agent_spec()

        def _sort_key(name: str) -> int:
            s = spec_map.get(name, {})
            role = str(s.get("role") or "").strip() if isinstance(s, dict) else ""
            return role_order.get(role, 50)

        agent_names.sort(key=_sort_key)

        started = []
        for name in agent_names:
            if self._launcher.is_running(name):
                continue
            result = self._launcher.restart(name, reason=reason)
            if result.success:
                started.append(name)

        self._audit.log_event("wake_group_complete", {
            "group": group_name,
            "policy": policy,
            "reason": reason,
            "started": started,
            "total_in_group": len(agent_names),
        })

    def _wake_agent(self, agent_name: str, reason: str = "wake_on_demand") -> None:
        """Wake a single agent (checks its group's wake_policy)."""
        spec_map = self._launcher.get_agent_spec()
        agent_spec = spec_map.get(agent_name)
        if not agent_spec or not isinstance(agent_spec, dict):
            raise ValueError(f"unknown agent: {agent_name}")

        group_name = str(agent_spec.get("_group") or agent_spec.get("group") or "").strip()
        if not group_name:
            raise ValueError(f"agent '{agent_name}' has no group")

        meta = self._get_group_meta().get(group_name)
        policy = str(meta.get("wake_policy") or "manual").strip() if meta else "manual"
        if policy == "manual":
            raise ValueError(f"agent '{agent_name}' belongs to group '{group_name}' with wake_policy=manual")

        if self._launcher.is_running(agent_name):
            self._audit.log_event("wake_agent_already_running", {"agent": agent_name, "group": group_name})
            return

        result = self._launcher.restart(agent_name, reason=reason)
        self._audit.log_event("wake_agent_complete", {
            "agent": agent_name,
            "group": group_name,
            "policy": policy,
            "reason": reason,
            "success": result.success,
        })

    def _handle_control_command(self, ev: InboundEvent) -> None:
        payload = ev.payload
        from_agent = self._parse_agent_name(ev.from_agent)
        if from_agent not in self._allowed_control_senders:
            self._audit.log_event("control_command_rejected", {"from": ev.from_agent, "payload": payload})
            return

        cmd = str(payload.get("cmd") or "").strip()
        agent = str(payload.get("agent") or "").strip()
        reason = str(payload.get("reason") or "ipc_command").strip()
        spec = payload.get("spec") or {}
        self._audit.log_event("control_command_received", {"from": ev.from_agent, "cmd": cmd, "agent": agent})

        try:
            if cmd in ("reconcile", "check"):
                self._launcher.reconcile()
            elif cmd in ("reload", "reload_config"):
                self._launcher.reload_config()
                self._config.reload()
            elif cmd == "restart":
                self._launcher.set_desired_state(agent, "running")
                self._launcher.restart(agent, reason=reason)
            elif cmd == "start":
                self._launcher.set_desired_state(agent, "running")
                self._launcher.restart(agent, reason=reason)
            elif cmd == "stop":
                self._launcher.stop(agent, reason=reason, persist_desired_state=True)
            elif cmd == "provision_agent":
                if not isinstance(spec, dict):
                    raise ValueError("spec must be a mapping")
                self._provisioner.provision_agent(spec)
            elif cmd == "wake_group":
                group = str(payload.get("group") or "").strip()
                if not group:
                    raise ValueError("wake_group requires 'group' field")
                self._wake_group(group, reason=reason)
            elif cmd == "wake_agent":
                if not agent:
                    raise ValueError("wake_agent requires 'agent' field")
                self._wake_agent(agent, reason=reason)
            else:
                raise ValueError(f"unknown cmd: {cmd}")
            self._audit.log_event("control_command_executed", {"cmd": cmd, "agent": agent})
        except Exception as e:
            self._audit.log_event("control_command_error", {"cmd": cmd, "agent": agent, "error": str(e)})

    async def _handle_user_message(self, ev: InboundEvent) -> None:
        payload = ev.payload
        user_id = str(payload.get("user_id") or "")
        text = str(payload.get("text") or payload.get("message") or "")
        if not text:
            # Alerts from internal health/config checks
            if payload.get("event_type") == "orchestrator_alert" and payload.get("content"):
                content = str(payload.get("content") or "")
                kind = str(payload.get("kind") or "")
                agent = str(payload.get("agent") or "")
                self._audit.log_event("system_alert_received", {"from": ev.from_agent, "content_preview": content[:200]})
                self._notify_admins(content, kind=kind, agent=agent)
            return

        task_id = str(payload.get("task_id") or _default_task_id(payload))
        route_decision_id = uuid.uuid4().hex[:12]

        if not self._mark_seen(task_id):
            self._audit.log_event("duplicate_task_dropped", {"from": ev.from_agent, "msg_id": ev.msg_id}, task_id=task_id, route_decision_id=route_decision_id)
            return

        self._audit.log_event("inbound_received", {"from": ev.from_agent, "msg_id": ev.msg_id, "text_preview": text[:120]}, task_id=task_id, route_decision_id=route_decision_id, user_id=user_id or None)

        if _is_command(text):
            command, args = _split_command(text)
            result = self._commands.handle(command, args, {"user_id": user_id})
            self._send_user_reply(payload, result.content)
            self._audit.log_event("command_replied", {"command": command, "restricted_used": result.restricted_used, "success": result.success}, task_id=task_id, route_decision_id=route_decision_id, user_id=user_id or None)
            return

        decision: RouteDecision = self._router.route(text, {"user_id": user_id, "group_id": payload.get("group_id"), "project_id": payload.get("project_id")})
        self._audit.log_event("route_decision", {"target_agent": decision.target_agent, "reason": decision.reason, "matched_rule": decision.matched_rule, "fallback_chain": decision.fallback_chain}, task_id=task_id, route_decision_id=route_decision_id, user_id=user_id or None)

        ctx = {"task_id": task_id, "route_decision_id": route_decision_id, "user_id": user_id, "chat_id": payload.get("chat_id"), "message_id": payload.get("message_id"), "platform": payload.get("platform")}
        result = await self._dispatcher.dispatch(decision, text, ctx)
        if result.status == "success":
            self._send_user_reply(payload, result.content)
        else:
            msg = f"⚠️ 请求处理失败（{result.status}）。task_id={task_id}"
            if result.error:
                msg += f"\nerror={result.error}"
            self._send_user_reply(payload, msg)

    def _validate_config_or_alert(self) -> bool:
        try:
            issues = validate_agents_registry(self._config.get_agents_registry())
            errors = [i for i in issues if i.level == "error"]
            if not errors:
                self._last_config_error_sig = None
                return True
            sig = "|".join([f"{e.agent}:{e.message}" for e in errors])[:600]
            if sig != self._last_config_error_sig:
                self._last_config_error_sig = sig
                self._notify_admins(f"[brain-agentctl] agents_registry.yaml invalid: {sig}", kind="config_invalid")
            return False
        except Exception:
            return True

    def _orchestrator_tick(self) -> None:
        if not self._validate_config_or_alert():
            return
        results = self._launcher.reconcile()
        issues = self._health.detect(results)
        for issue in issues:
            self._notify_admins(
                f"[brain-agentctl] {issue.kind} agent={issue.agent_name} detail={issue.detail}",
                kind=issue.kind,
                agent=issue.agent_name,
            )

    async def run_forever(self) -> None:
        # Cleanup stale sessions before starting main loop
        if self._cleanup_before_start:
            try:
                result = self._launcher.stop_all_managed_agents()
                self._audit.log_event("startup_cleanup_complete", {
                    "stopped": result.stopped,
                    "failed": result.failed,
                    "skipped_attached": result.skipped_attached,
                    "total_time_seconds": result.total_time_seconds,
                })
                if result.failed:
                    self._notify_admins(
                        f"[brain-agentctl] Startup cleanup: {len(result.stopped)} stopped, {len(result.failed)} failed: {result.failed}",
                        kind="cleanup_partial_failure",
                    )
            except Exception as e:
                self._audit.log_event("startup_cleanup_error", {"error": str(e)})
                # Non-blocking: continue startup even if cleanup fails

        # Register self as service
        try:
            self._daemon.register_service(self._agent_name, {"type": "agentctl"})
            self._audit.log_event("service_registered", {"service_name": self._agent_name})
        except Exception as e:
            self._audit.log_event("service_register_error", {"error": str(e)})

        # Run recovery coordination (restart agents in order)
        try:
            recovery_result = await self._coordinator.coordinate_recovery()
            self._audit.log_event("startup_recovery_complete", {
                "run_id": recovery_result.run_id,
                "status": recovery_result.status.value,
                "ready": recovery_result.ready_count,
                "failed": recovery_result.failed_count,
                "duration_s": recovery_result.duration_seconds,
            })
            if recovery_result.failed_agents:
                self._notify_admins(
                    f"[brain-agentctl] Recovery: {recovery_result.ready_count} ready, {recovery_result.failed_count} failed: {recovery_result.failed_agents}",
                    kind="recovery_partial_failure",
                )
        except Exception as e:
            self._audit.log_event("startup_recovery_error", {"error": str(e)})
            # Non-blocking: continue even if recovery fails

        notify = NotifyClient(self._agent_name)

        async def _ipc_listener() -> None:
            """Wait for push notifications, then fetch and process messages."""
            async for _event in notify.listen():
                try:
                    await self._drain_messages()
                except Exception as e:
                    self._audit.log_event("agentctl_loop_error", {"error": str(e)})

        async def _orchestrator_loop() -> None:
            """Periodic orchestrator tick (health checks, auto-restart)."""
            while True:
                await asyncio.sleep(float(self._orchestrator_interval_s))
                try:
                    self._orchestrator_tick()
                except Exception as e:
                    self._audit.log_event("orchestrator_tick_error", {"error": str(e)})

        # Drain any messages queued before we connected to notify socket
        try:
            await self._drain_messages()
        except Exception as e:
            self._audit.log_event("agentctl_initial_drain_error", {"error": str(e)})

        await asyncio.gather(_ipc_listener(), _orchestrator_loop())

    async def _drain_messages(self) -> None:
        """Fetch and process all pending IPC messages."""
        resp = self._daemon.recv(agent_name=self._agent_name, ack_mode="manual", max_items=20)
        msgs = resp.get("messages", []) or []
        ack_ids: list[str] = []

        for m in msgs:
            if not isinstance(m, dict):
                continue
            msg_id = str(m.get("msg_id") or "")
            if msg_id:
                ack_ids.append(msg_id)
            from_agent = str(m.get("from") or "")
            payload = m.get("payload", {}) or {}
            if not isinstance(payload, dict):
                payload = {}

            ev = InboundEvent(msg_id=msg_id, from_agent=from_agent, payload=payload)
            if "cmd" in payload:
                self._handle_control_command(ev)
            else:
                await self._handle_user_message(ev)

        if ack_ids:
            self._daemon.ack(self._agent_name, ack_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Brain AgentCTL Service (unified agent lifecycle manager)")
    parser.add_argument("--agent-name", default=os.environ.get("AGENTCTL_SERVICE_NAME", os.environ.get("AGENT_ORCHESTRATOR_NAME", "service-agentctl")))
    parser.add_argument("--daemon-socket", default=os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock"))
    parser.add_argument("--config-dir", default=os.environ.get("AGENT_MANAGER_CONFIG_DIR", str(DEFAULT_CONFIG_DIR)))
    parser.add_argument("--poll-interval-ms", type=int, default=int(os.environ.get("AGENT_MANAGER_POLL_MS", "200")))
    parser.add_argument("--outbound-agent", default=os.environ.get("AGENT_MANAGER_OUTBOUND_AGENT", "service_gateway_telegram"))
    parser.add_argument("--telegram-max-chars", type=int, default=int(os.environ.get("TELEGRAM_MAX_CHARS", "3500")))
    parser.add_argument("--orchestrator-interval", type=int, default=int(os.environ.get("ORCHESTRATOR_INTERVAL_S", "10")))
    parser.add_argument("--cleanup-before-start", action="store_true", default=os.environ.get("CLEANUP_BEFORE_START", "true").lower() in ("1", "true", "yes"))
    parser.add_argument("--cleanup-timeout", type=int, default=int(os.environ.get("CLEANUP_TIMEOUT_S", "5")))
    parser.add_argument("--cleanup-skip-attached", action="store_true", default=os.environ.get("CLEANUP_SKIP_ATTACHED", "true").lower() in ("1", "true", "yes"))
    args = parser.parse_args()

    loader = YAMLConfigLoader(config_dir=Path(args.config_dir))
    audit = AuditLogger(agent_name=args.agent_name, session=os.environ.get("TMUX_SESSION", ""))
    daemon = BrainDaemonClient(socket_path=args.daemon_socket)

    svc = AgentCtlService(
        agent_name=args.agent_name,
        daemon=daemon,
        config_loader=loader,
        audit=audit,
        poll_interval_s=max(0.05, args.poll_interval_ms / 1000.0),
        outbound_agent=args.outbound_agent,
        telegram_max_chars=args.telegram_max_chars,
        orchestrator_interval_s=max(2, int(args.orchestrator_interval)),
        cleanup_before_start=args.cleanup_before_start,
        cleanup_timeout_seconds=max(1, args.cleanup_timeout),
        cleanup_skip_attached=args.cleanup_skip_attached,
    )
    asyncio.run(svc.run_forever())


if __name__ == "__main__":
    main()
