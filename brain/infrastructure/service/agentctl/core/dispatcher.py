from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from core.router import RouteDecision
from services.audit_logger import AuditLogger
from services.target_resolver import AmbiguousTarget, TargetResolver

# SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
BrainDaemonClient = _mod.BrainDaemonClient
IPCError = _mod.IPCError


@dataclass(frozen=True)
class DispatchResult:
    status: str  # success | error | timeout
    content: str
    elapsed_ms: int
    error: str | None = None


class Dispatcher:
    def __init__(
        self,
        daemon: BrainDaemonClient,
        audit: AuditLogger,
        manager_agent_name: str = "manager",
        target_resolver: TargetResolver | None = None,
        config_loader: Any | None = None,
    ) -> None:
        self._daemon = daemon
        self._audit = audit
        self._manager_agent_name = manager_agent_name
        self._config_loader = config_loader
        self._resolver = target_resolver or TargetResolver(daemon, config_loader=config_loader)  # type: ignore[arg-type]

    async def dispatch(self, decision: RouteDecision, message: str, ctx: dict[str, Any]) -> DispatchResult:
        task_id = str(ctx.get("task_id") or "")
        route_decision_id = str(ctx.get("route_decision_id") or "")
        user_id = str(ctx.get("user_id") or "")

        timeout_ms = int(ctx.get("timeout_ms") or 60000)
        max_retries = int(ctx.get("max_retries") or 2)
        backoff_ms = ctx.get("backoff_ms") or [500, 1500]
        if not isinstance(backoff_ms, list):
            backoff_ms = [500, 1500]

        candidates = [decision.target_agent] + list(decision.fallback_chain or [])
        last_error: str | None = None

        start = time.perf_counter()
        for idx, target in enumerate(candidates):
            if not self._telegram_allowed(target):
                last_error = f"telegram access disabled for agent '{target}'"
                self._audit.log_event(
                    "telegram_access_blocked",
                    {"requested": target},
                    task_id=task_id or None,
                    route_decision_id=route_decision_id or None,
                    user_id=user_id or None,
                )
                continue
            try:
                resolved = self._resolver.resolve(target)
                to_agent = resolved.resolved
            except AmbiguousTarget as e:
                last_error = str(e)
                self._audit.log_event(
                    "target_ambiguous",
                    {"requested": e.requested, "candidates": e.candidates},
                    task_id=task_id or None,
                    route_decision_id=route_decision_id or None,
                    user_id=user_id or None,
                )
                continue
            except Exception as e:
                last_error = f"target resolution failed for '{target}': {e}"
                self._audit.log_event(
                    "target_resolution_error",
                    {"requested": target, "error": str(e)},
                    task_id=task_id or None,
                    route_decision_id=route_decision_id or None,
                    user_id=user_id or None,
                )
                continue

            attempts = max_retries + 1 if idx == 0 else 1
            for attempt in range(1, attempts + 1):
                try:
                    self._audit.log_event(
                        "message_forward_attempt",
                        {"to": to_agent, "requested": target, "attempt": attempt, "candidate_index": idx},
                        task_id=task_id or None,
                        route_decision_id=route_decision_id or None,
                        user_id=user_id or None,
                    )

                    self._daemon.send(
                        from_agent=self._manager_agent_name,
                        to_agent=to_agent,
                        payload={
                            "task_id": task_id,
                            "user_id": user_id,
                            "message": message,
                            "context": {
                                **{k: v for k, v in ctx.items() if k not in ("message",)},
                                "route_decision_id": route_decision_id,
                                "reply_to": self._manager_agent_name,
                            },
                        },
                        message_type="request",
                    )

                    reply = await self._wait_for_reply(task_id=task_id, timeout_ms=timeout_ms)
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    self._audit.log_event(
                        "message_forward_success",
                        {"to": to_agent, "requested": target, "elapsed_ms": elapsed_ms},
                        task_id=task_id or None,
                        route_decision_id=route_decision_id or None,
                        user_id=user_id or None,
                    )
                    return DispatchResult(status="success", content=reply, elapsed_ms=elapsed_ms)
                except asyncio.TimeoutError:
                    last_error = f"timeout waiting reply from {to_agent} (requested={target})"
                    self._audit.log_event(
                        "message_forward_timeout",
                        {"to": to_agent, "requested": target, "attempt": attempt, "timeout_ms": timeout_ms},
                        task_id=task_id or None,
                        route_decision_id=route_decision_id or None,
                        user_id=user_id or None,
                    )
                except Exception as e:
                    last_error = str(e)
                    self._audit.log_event(
                        "message_forward_error",
                        {"to": to_agent, "requested": target, "attempt": attempt, "error": last_error},
                        task_id=task_id or None,
                        route_decision_id=route_decision_id or None,
                        user_id=user_id or None,
                    )

                if attempt <= len(backoff_ms):
                    await asyncio.sleep(float(backoff_ms[attempt - 1]) / 1000.0)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return DispatchResult(
            status="error" if last_error else "timeout",
            content="",
            elapsed_ms=elapsed_ms,
            error=last_error,
        )

    def _telegram_allowed(self, logical_agent: str) -> bool:
        """Gate which agents are allowed to receive Telegram-routed traffic.

        Configuration is in agents_registry.yaml under agents[].telegram_enabled (default: true).
        """
        try:
            cfg = self._config_loader
            if cfg is None:
                return True
            data = cfg.get_agents_registry()
            root = data.get("agents_registry", {}) if isinstance(data, dict) else {}
            agents = root.get("agents", []) if isinstance(root, dict) else []
            if not isinstance(agents, list):
                return True
            for a in agents:
                if not isinstance(a, dict):
                    continue
                if str(a.get("name") or "").strip() != str(logical_agent or "").strip():
                    continue
                v = a.get("telegram_enabled", True)
                return bool(v) if isinstance(v, bool) else True
        except Exception:
            return True
        return True

    async def _wait_for_reply(self, task_id: str, timeout_ms: int) -> str:
        """Wait for an agent reply addressed to manager with matching task_id.

        Contract expectation:
          - Agents reply via IPC to `to=manager` with payload including task_id and content.
        """

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()

            response = self._daemon.recv(
                agent_name=self._manager_agent_name,
                ack_mode="manual",
                max_items=10,
            )
            messages = response.get("messages", []) or []
            if not isinstance(messages, list):
                messages = []

            acked: list[str] = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("msg_id") or "")
                payload = msg.get("payload", {}) or {}
                if msg_id:
                    acked.append(msg_id)

                if not isinstance(payload, dict):
                    continue
                if str(payload.get("task_id") or "") != task_id:
                    continue
                content = str(payload.get("content") or payload.get("message") or "")
                if acked:
                    self._daemon.ack(self._manager_agent_name, acked)
                return content

            if acked:
                self._daemon.ack(self._manager_agent_name, acked)

            await asyncio.sleep(min(0.2, remaining))
