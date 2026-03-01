from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogError(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class AuditSinks:
    global_jsonl: Path
    project_jsonl: Path


def default_sinks() -> AuditSinks:
    date = _date_utc()
    global_path = Path(
        os.environ.get(
            "AGENTCTL_AUDIT_GLOBAL",
            os.environ.get(
                "AGENT_ORCHESTRATOR_AUDIT_GLOBAL",  # fallback for backward compatibility
                f"/xkagent_infra/brain/runtime/logs/agents/global_agent_log_{date}.jsonl",
            )
        )
    )
    project_path = Path(
        os.environ.get(
            "AGENTCTL_AUDIT_PROJECT",
            os.environ.get(
                "AGENT_ORCHESTRATOR_AUDIT_PROJECT",  # fallback for backward compatibility
                f"/xkagent_infra/app/memory/audit/agentctl_audit_{date}.jsonl",
            )
        )
    )
    return AuditSinks(global_jsonl=global_path, project_jsonl=project_path)


class AuditLogger:
    """Append-only JSONL audit logger with dual sinks and date-based rotation.

    Rotation strategy:
      - sinks are resolved at construction; call rotate_if_needed() per event
        to switch to a new {date} file without restarting.
    """

    def __init__(self, agent_name: str, session: str = "", sinks: AuditSinks | None = None) -> None:
        self._agent_name = agent_name
        self._session = session
        self._lock = threading.Lock()
        self._date = _date_utc()
        self._sinks = sinks or default_sinks()

    def rotate_if_needed(self) -> None:
        date = _date_utc()
        if date == self._date:
            return
        with self._lock:
            date = _date_utc()
            if date == self._date:
                return
            self._date = date
            self._sinks = default_sinks()

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        route_decision_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.rotate_if_needed()

        record: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "agent": self._agent_name,
            "session": self._session,
            "event_type": event_type,
            "payload": payload,
        }
        if task_id is not None:
            record["task_id"] = task_id
        if route_decision_id is not None:
            record["route_decision_id"] = route_decision_id
        if user_id is not None:
            record["user_id"] = user_id

        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"

        with self._lock:
            self._append(self._sinks.global_jsonl, line)
            self._append(self._sinks.project_jsonl, line)

    def _append(self, path: Path, line: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:  # pragma: no cover
            raise AuditLogError(f"Failed to write audit log: {path}: {e}") from e
