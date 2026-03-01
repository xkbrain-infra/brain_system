#!/usr/bin/env python3
"""Service Timer - IPC timer scheduler.

Supports interval and cron jobs loaded from timers.yaml.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import yaml
from croniter import croniter

from timer.daemon_client import DaemonClient
from timer.ipc_reliability import MessageStateStore, MessageStatus


DEFAULT_CONFIG = "/xkagent_infra/brain/infrastructure/config/timers.yaml"
DEFAULT_IPC_STATE_DB = "/xkagent_infra/brain/infrastructure/data/db/ipc_state.db"
DEFAULT_SOCKET = "/tmp/brain_ipc.sock"
DEFAULT_AGENT_NAME = "service-brain_timer"
DEFAULT_HEALTH_PORT = 8090
DEFAULT_RELOAD_INTERVAL = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("service-brain_timer")
_HEALTH_STATE: dict[str, Any] = {
    "status": "starting",
    "service": "service-brain_timer",
    "jobs_loaded": 0,
    "last_reload_ts": None,
    "last_tick_ts": None,
}


@dataclass
class TimerAction:
    to: str
    message_type: str = "request"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimerJob:
    job_id: str
    job_type: str  # interval | cron
    every_seconds: float | None = None
    cron: str | None = None
    action: TimerAction | None = None
    enabled: bool = True
    next_run: float | None = None
    running: bool = False
    last_fired: float | None = None
    max_retries: int = 0
    retry_backoff_seconds: float = 1.0
    timeout_seconds: float = 6.0
    min_interval_seconds: float = 0.0


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(_HEALTH_STATE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class ServiceTimer:
    def __init__(
        self,
        config_path: str,
        socket_path: str,
        agent_name: str,
        health_port: int,
        reload_interval: float,
        ipc_state_db: str = DEFAULT_IPC_STATE_DB,
        reliability_sweep_interval: float = 5.0,
    ) -> None:
        self._config_path = config_path
        self._daemon = DaemonClient(socket_path)
        self._agent_name = agent_name
        self._health_port = health_port
        self._reload_interval = reload_interval
        self._reload_flag = False
        self._jobs: dict[str, TimerJob] = {}
        self._last_reload_ts: float = 0.0
        self._config_mtime: float = 0.0
        # IPC Reliability
        self._state_store = MessageStateStore(db_path=ipc_state_db)
        self._reliability_sweep_interval = reliability_sweep_interval
        self._last_reliability_sweep: float = 0.0

    def _handle_sighup(self, *_: Any) -> None:
        logger.info("Reload requested (SIGHUP)")
        self._reload_flag = True

    def _start_health_server(self) -> None:
        server = HTTPServer(("0.0.0.0", self._health_port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Health server started on port %s", self._health_port)

    def _load_config(self) -> dict[str, Any]:
        if not os.path.exists(self._config_path):
            logger.warning("Config not found: %s", self._config_path)
            return {}
        try:
            self._config_mtime = os.path.getmtime(self._config_path)
        except Exception:
            self._config_mtime = 0.0
        with open(self._config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data

    def _validate_job(self, item: dict[str, Any]) -> bool:
        job_id = str(item.get("id") or "").strip()
        job_type = str(item.get("type") or "").strip()
        if not job_id:
            logger.warning("Job missing id")
            return False
        if job_type not in ("interval", "cron"):
            logger.warning("Job %s invalid type: %s", job_id, job_type)
            return False
        action = item.get("action") or {}
        if not isinstance(action, dict):
            logger.warning("Job %s action must be mapping", job_id)
            return False
        target = str(action.get("to") or "").strip()
        if not target:
            logger.warning("Job %s action.to required", job_id)
            return False
        if job_type == "interval":
            try:
                every = float(item.get("every_seconds", 0) or 0)
            except Exception:
                every = 0
            if every <= 0:
                logger.warning("Job %s invalid every_seconds", job_id)
                return False
        if job_type == "cron":
            cron_expr = str(item.get("cron") or "").strip()
            if not cron_expr:
                logger.warning("Job %s missing cron", job_id)
                return False
            try:
                croniter(cron_expr, time.time())
            except Exception:
                logger.warning("Job %s invalid cron: %s", job_id, cron_expr)
                return False
        return True

    def _parse_jobs(self, data: dict[str, Any]) -> dict[str, TimerJob]:
        jobs: dict[str, TimerJob] = {}
        items = data.get("timers", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return jobs

        for item in items:
            if not isinstance(item, dict):
                continue
            if not self._validate_job(item):
                continue
            job_id = str(item.get("id") or "").strip()
            if not job_id:
                continue
            job_type = str(item.get("type") or "").strip()
            enabled = bool(item.get("enabled", True))

            action_raw = item.get("action") or {}
            if not isinstance(action_raw, dict):
                action_raw = {}
            action = TimerAction(
                to=str(action_raw.get("to") or "").strip(),
                message_type=str(action_raw.get("message_type") or "request"),
                payload=action_raw.get("payload") if isinstance(action_raw.get("payload"), dict) else {},
            )

            max_retries = int(item.get("max_retries", 0) or 0)
            retry_backoff = float(item.get("retry_backoff_seconds", 1.0) or 1.0)
            timeout_seconds = float(item.get("timeout_seconds", 6.0) or 6.0)
            min_interval_seconds = float(item.get("min_interval_seconds", 0.0) or 0.0)

            job = TimerJob(
                job_id=job_id,
                job_type=job_type,
                enabled=enabled,
                action=action,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff,
                timeout_seconds=timeout_seconds,
                min_interval_seconds=min_interval_seconds,
            )

            if job_type == "interval":
                job.every_seconds = float(item.get("every_seconds", 0) or 0)
                if job.every_seconds <= 0:
                    logger.warning("Invalid interval for %s", job_id)
                    continue
                job.next_run = time.time() + job.every_seconds
            elif job_type == "cron":
                job.cron = str(item.get("cron") or "").strip()
                if not job.cron:
                    logger.warning("Missing cron for %s", job_id)
                    continue
                job.next_run = self._next_cron(job.cron)
            else:
                logger.warning("Unknown job type '%s' for %s", job_type, job_id)
                continue

            jobs[job_id] = job

        return jobs

    def _next_cron(self, expr: str, base_ts: float | None = None) -> float:
        base = base_ts if base_ts is not None else time.time()
        it = croniter(expr, base)
        return float(it.get_next(float))

    async def _execute_job(self, job: TimerJob) -> None:
        if not job.action or not job.action.to:
            logger.warning("Job %s missing action target", job.job_id)
            return
        job.running = True
        try:
            attempt = 0
            while True:
                attempt += 1
                try:
                    payload = {
                        **(job.action.payload or {}),
                        "timer_id": job.job_id,
                        "event_type": "timer_trigger",
                    }
                    send_call = lambda: self._daemon.send(
                        from_agent=self._agent_name,
                        to_agent=job.action.to,
                        payload=payload,
                        message_type=job.action.message_type or "request",
                    )
                    await asyncio.wait_for(
                        asyncio.to_thread(send_call),
                        timeout=job.timeout_seconds if job.timeout_seconds > 0 else 6.0,
                    )
                    logger.info("Job %s fired -> %s", job.job_id, job.action.to)
                    break
                except Exception as e:
                    logger.error("Job %s attempt %s failed: %s", job.job_id, attempt, e)
                    if attempt > job.max_retries:
                        break
                    await asyncio.sleep(job.retry_backoff_seconds)
        finally:
            job.running = False

    def _schedule_next(self, job: TimerJob, now: float) -> None:
        if job.job_type == "interval" and job.every_seconds:
            job.next_run = now + job.every_seconds
        elif job.job_type == "cron" and job.cron:
            job.next_run = self._next_cron(job.cron, base_ts=now)

    async def _run_reliability_sweep(self) -> None:
        """Sweep for timed-out messages and trigger retries."""
        try:
            now = time.time()
            pending_timeouts = self._state_store.get_pending_timeouts(now)

            for msg in pending_timeouts:
                if msg.status in (MessageStatus.SENT, MessageStatus.RETRIED):
                    # Check if can retry
                    updated, new_deadline = self._state_store.mark_retried(msg.message_id)
                    if updated:
                        # Retry send
                        try:
                            payload = json.loads(msg.payload) if msg.payload else {}
                            payload["_retry_attempt"] = msg.attempt_count + 1
                            payload["_original_msg_id"] = msg.message_id
                            await asyncio.to_thread(
                                self._daemon.send,
                                from_agent=msg.from_agent,
                                to_agent=msg.target,
                                payload=payload,
                                conversation_id=msg.conversation_id,
                                message_type=msg.message_type,
                            )
                            logger.info(
                                "Reliability retry: %s -> %s (attempt %d)",
                                msg.message_id,
                                msg.target,
                                msg.attempt_count + 1,
                            )
                        except Exception as e:
                            logger.error("Retry send failed for %s: %s", msg.message_id, e)
                    else:
                        logger.warning("Message %s exceeded retry limits", msg.message_id)

            # Periodic cleanup
            if now - self._last_reliability_sweep > 3600:  # Every hour
                self._state_store.cleanup_old()

        except Exception as e:
            logger.error("Reliability sweep error: %s", e)

    async def run(self) -> None:
        signal.signal(signal.SIGHUP, self._handle_sighup)
        self._start_health_server()

        # Register service
        try:
            self._daemon.register(self._agent_name, {"type": "service-brain_timer"})
        except Exception as e:
            logger.error("Failed to register service: %s", e)

        # Initial load
        self._jobs = self._parse_jobs(self._load_config())
        self._last_reload_ts = time.time()
        _HEALTH_STATE.update({
            "status": "ok",
            "jobs_loaded": len(self._jobs),
            "last_reload_ts": self._last_reload_ts,
        })
        logger.info("Loaded %s jobs", len(self._jobs))

        while True:
            now = time.time()

            if self._reload_flag:
                self._reload_flag = False
                self._jobs = self._parse_jobs(self._load_config())
                self._last_reload_ts = time.time()
                _HEALTH_STATE.update({
                    "jobs_loaded": len(self._jobs),
                    "last_reload_ts": self._last_reload_ts,
                })
                logger.info("Reloaded %s jobs", len(self._jobs))

            if now - self._last_reload_ts >= self._reload_interval:
                try:
                    mtime = os.path.getmtime(self._config_path)
                except Exception:
                    mtime = 0.0
                if mtime > self._config_mtime:
                    self._jobs = self._parse_jobs(self._load_config())
                    self._last_reload_ts = time.time()
                    _HEALTH_STATE.update({
                        "jobs_loaded": len(self._jobs),
                        "last_reload_ts": self._last_reload_ts,
                    })
                    logger.info("Auto-reloaded %s jobs", len(self._jobs))

            _HEALTH_STATE["last_tick_ts"] = now
            _HEALTH_STATE["ipc_reliability"] = self._state_store.get_stats()
            for job in list(self._jobs.values()):
                if not job.enabled:
                    continue
                if job.next_run is None:
                    continue
                if now >= job.next_run:
                    if job.last_fired and job.min_interval_seconds > 0:
                        if now - job.last_fired < job.min_interval_seconds:
                            self._schedule_next(job, now)
                            continue
                    if job.running:
                        logger.warning("Job %s skipped (still running)", job.job_id)
                    else:
                        asyncio.create_task(self._execute_job(job))
                        job.last_fired = now
                    self._schedule_next(job, now)

            # IPC Reliability sweep
            if now - self._last_reliability_sweep >= self._reliability_sweep_interval:
                asyncio.create_task(self._run_reliability_sweep())
                self._last_reliability_sweep = now

            await asyncio.sleep(0.5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IPC Service Timer")
    parser.add_argument("--config", default=os.environ.get("TIMER_CONFIG", DEFAULT_CONFIG))
    parser.add_argument("--socket", default=os.environ.get("DAEMON_SOCKET", DEFAULT_SOCKET))
    parser.add_argument("--agent-name", default=os.environ.get("TIMER_AGENT_NAME", DEFAULT_AGENT_NAME))
    parser.add_argument("--health-port", type=int, default=int(os.environ.get("TIMER_HEALTH_PORT", DEFAULT_HEALTH_PORT)))
    parser.add_argument("--reload-interval", type=float, default=float(os.environ.get("TIMER_RELOAD_INTERVAL", DEFAULT_RELOAD_INTERVAL)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    svc = ServiceTimer(
        config_path=args.config,
        socket_path=args.socket,
        agent_name=args.agent_name,
        health_port=args.health_port,
        reload_interval=args.reload_interval,
    )
    asyncio.run(svc.run())


if __name__ == "__main__":
    main()
