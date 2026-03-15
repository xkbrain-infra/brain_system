#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util as _ilu
import time
from datetime import datetime
from typing import Any

from services.audit_logger import AuditLogger
from services.health import HealthMonitor
from services.launcher import Launcher
from services.notifier import Notifier
from services.provisioner import Provisioner
from config.loader import DEFAULT_CONFIG_DIR, YAMLConfigLoader
from config.validator import validate_agents_registry

# SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_DaemonClient = _mod.DaemonClient


class ServiceAgentOrchestrator:
    def __init__(self, *, agent_name: str, interval_s: int = 10) -> None:
        self.agent_name = agent_name
        self.interval_s = interval_s
        self.audit = AuditLogger(agent_name=agent_name, session="")

        self._config = YAMLConfigLoader(config_dir=DEFAULT_CONFIG_DIR)
        self.launcher = Launcher(self_name=agent_name, check_interval_s=interval_s, audit_logger=self.audit)
        self.health = HealthMonitor()
        self.notifier = Notifier(from_agent=agent_name, manager_agent="manager", audit_logger=self.audit)
        self.provisioner = Provisioner(audit_logger=self.audit, config_loader=self._config, launcher=self.launcher)

        self._allowed_senders = self._load_allowed_senders()
        self._last_config_error_sig: str | None = None
        self._ipc = _DaemonClient()

    def _load_allowed_senders(self) -> set[str]:
        try:
            cfg = self._config.get_whitelist()
            root = cfg.get("whitelist", {}) if isinstance(cfg, dict) else {}
            ipc = root.get("ipc_control", {}) if isinstance(root, dict) else {}
            allowed = ipc.get("allowed_from_agents", []) if isinstance(ipc, dict) else []
            if isinstance(allowed, list):
                out = {str(x).strip() for x in allowed if str(x).strip()}
                if out:
                    return out
        except Exception:
            pass
        return {"manager"}  # safe default

    def _ts(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _daemon_request(self, action: str, data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._ipc._send_request(action, data)
        except Exception:
            return None

    def _parse_agent_name(self, instance_id_or_name: str) -> str:
        s = (instance_id_or_name or "").strip()
        return s.split("@", 1)[0] if s else ""

    def _poll_ipc_commands(self) -> None:
        """Poll IPC commands with transaction handling and error recovery."""
        try:
            resp = self._daemon_request(
                "ipc_recv",
                {"agent": self.agent_name, "ack_mode": "manual", "max_items": 20},
            )
            if not isinstance(resp, dict) or resp.get("status") != "ok":
                return
            
            messages = resp.get("messages", []) or []
            if not isinstance(messages, list) or not messages:
                return

            ack_ids: list[str] = []
            processed_ids: list[str] = []
            
            for m in messages:
                if not isinstance(m, dict):
                    continue
                    
                msg_id = str(m.get("msg_id") or "")
                if not msg_id:
                    continue
                    
                from_ = str(m.get("from") or "")
                from_agent = self._parse_agent_name(from_)
                payload = m.get("payload", {}) or {}
                if not isinstance(payload, dict):
                    payload = {}

                # Validate sender
                if from_agent and from_agent not in self._allowed_senders:
                    self.audit.log_event("orchestrator_command_rejected", 
                                       {"from": from_, "payload": payload, "msg_id": msg_id})
                    ack_ids.append(msg_id)  # Acknowledge but don't process
                    continue

                cmd = str(payload.get("cmd") or "").strip()
                agent = str(payload.get("agent") or "").strip()
                reason = str(payload.get("reason") or "ipc_command").strip()

                self.audit.log_event("orchestrator_command_received", 
                                   {"from": from_, "cmd": cmd, "agent": agent, "msg_id": msg_id})

                # Process command with transaction handling
                try:
                    success = self._process_command(cmd, agent, reason, payload, from_, msg_id)
                    if success:
                        processed_ids.append(msg_id)
                        ack_ids.append(msg_id)
                    else:
                        # Don't ack failed commands to allow retry
                        self.audit.log_event("orchestrator_command_failed", 
                                           {"from": from_, "cmd": cmd, "agent": agent, "msg_id": msg_id})
                except Exception as e:
                    self.audit.log_event("orchestrator_command_error", 
                                       {"from": from_, "cmd": cmd, "agent": agent, "error": str(e), "msg_id": msg_id})
                    # Don't ack on error to allow retry

            # Batch ack processed messages
            if ack_ids:
                self._daemon_request("ipc_ack", {"agent": self.agent_name, "msg_ids": ack_ids})
                
        except Exception as e:
            self.audit.log_event("orchestrator_poll_error", {"error": str(e)})

    def _process_command(self, cmd: str, agent: str, reason: str, payload: dict, from_: str, msg_id: str) -> bool:
        """Process a single command with error handling."""
        try:
            if cmd in ("reconcile", "check"):
                self.launcher.reconcile()
            elif cmd in ("stats", "status"):
                return self._process_stats_command(from_)
            elif cmd in ("reload", "reload_config"):
                self.launcher.reload_config()
            elif cmd == "restart":
                self.launcher.set_desired_state(agent, "running")
                self.launcher.restart(agent, reason=reason)
            elif cmd == "start":
                self.launcher.set_desired_state(agent, "running")
                self.launcher.restart(agent, reason=reason)
            elif cmd == "stop":
                self.launcher.stop(agent, reason=reason, persist_desired_state=True)
            elif cmd == "provision_agent":
                self.provisioner.provision_agent(payload.get("spec") or {})
            else:
                raise ValueError(f"unknown cmd: {cmd}")
                
            self.audit.log_event("orchestrator_command_executed", 
                               {"from": from_, "cmd": cmd, "agent": agent, "msg_id": msg_id})
            return True
        except Exception as e:
            self.audit.log_event("orchestrator_command_error", 
                               {"from": from_, "cmd": cmd, "agent": agent, "error": str(e), "msg_id": msg_id})
            return False

    def _process_stats_command(self, from_: str) -> bool:
        """Process stats command with error handling."""
        try:
            online = self._daemon_request("agent_list", {"include_offline": False}) or {}
            instances = online.get("instances", []) if isinstance(online, dict) else []

            online_instances: list[dict[str, Any]] = []
            if isinstance(instances, list):
                for i in instances:
                    if not isinstance(i, dict):
                        continue
                    if not i.get("online"):
                        continue
                    online_instances.append(
                        {
                            "agent": str(i.get("agent_name") or ""),
                            "instance_id": str(i.get("instance_id") or ""),
                            "idle_seconds": int(i.get("idle_seconds") or 0),
                        }
                    )

            online_instances.sort(key=lambda x: (x.get("agent") or "", x.get("instance_id") or ""))
            online_instance_count = len(online_instances)
            online_agent_names = sorted({x.get("agent") for x in online_instances if x.get("agent")})
            online_agent_count = len(online_agent_names)

            spec = self.launcher.get_agent_spec()
            configured_total = len(spec)
            configured_required = len([1 for s in spec.values() if isinstance(s, dict) and bool(s.get("required", False))])
            configured_desired_running = len(
                [
                    1
                    for s in spec.values()
                    if isinstance(s, dict) and str(s.get("desired_state") or "running").strip().lower() == "running"
                ]
            )

            summary = {
                "online_instance_count": online_instance_count,
                "online_agent_count": online_agent_count,
                "online_agents": online_agent_names,
                "online_instances": online_instances,
                "configured_total": configured_total,
                "configured_required": configured_required,
                "configured_desired_running": configured_desired_running,
            }
            self.notifier.notify_manager(
                content=f"[orchestrator] online_instances={online_instance_count} online_agents={online_agent_count} configured={configured_total}",
                payload={"event_type": "orchestrator_stats", **summary},
            )
            return True
        except Exception as e:
            self.audit.log_event("orchestrator_stats_error", {"error": str(e)})
            return False

    def tick(self) -> None:
        self._poll_ipc_commands()

        # Validate SSOT before acting; avoid restart storms from bad config.
        try:
            issues = validate_agents_registry(self._config.get_agents_registry())
            errors = [i for i in issues if i.level == "error"]
            if errors:
                sig = "|".join([f"{e.agent}:{e.message}" for e in errors])[:600]
                if sig != self._last_config_error_sig:
                    self._last_config_error_sig = sig
                    self.notifier.notify_manager(
                        content=f"[orchestrator] agents_registry.yaml invalid: {sig}",
                        payload={"severity": "high", "kind": "config_invalid"},
                    )
                return
            self._last_config_error_sig = None
        except Exception:
            # If validation fails unexpectedly, do not block reconcile.
            pass

        results = self.launcher.reconcile()
        issues = self.health.detect(results)
        for issue in issues:
            self.notifier.notify_manager(
                content=f"[orchestrator] {issue.kind} agent={issue.agent_name} detail={issue.detail}",
                payload={"severity": issue.severity, "kind": issue.kind, "agent": issue.agent_name},
            )

    def run_forever(self) -> None:
        self.audit.log_event("orchestrator_started", {"interval_s": self.interval_s})
        while True:
            try:
                self.tick()
            except Exception as e:
                self.audit.log_event("orchestrator_loop_error", {"error": str(e)})
            time.sleep(self.interval_s)


def main() -> None:
    p = argparse.ArgumentParser(description="Service Agent Orchestrator")
    p.add_argument("--agent-name", default="service-agentctl")
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    orch = ServiceAgentOrchestrator(agent_name=args.agent_name, interval_s=args.interval)
    if args.once:
        orch.tick()
    else:
        orch.run_forever()


if __name__ == "__main__":
    main()
