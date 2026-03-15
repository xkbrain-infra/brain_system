#!/usr/bin/env python3
"""Agent Dashboard Service - Background monitoring daemon."""

import asyncio
import logging
import os
import signal
import time
from pathlib import Path

import yaml

from core.storage import Storage
from core.collector import Collector
from core.alerter import Alerter
from core.context_monitor import ContextMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent_dashboard")

# Globals
storage: Storage | None = None
collector: Collector | None = None
alerter: Alerter | None = None
context_monitor: ContextMonitor | None = None
config: dict = {}
running = True


def load_config() -> dict:
    """Load configuration from YAML."""
    config_path = os.environ.get(
        "DASHBOARD_CONFIG",
        "/brain/infrastructure/service/dashboard/config.yaml"
    )
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    logger.warning(f"Config not found: {config_path}, using defaults")
    return {}


def on_agent_collected(agent: dict, source: str) -> None:
    """Callback when an agent is collected (based on its interval)."""
    now = int(time.time())

    # Save snapshot with source type
    agent_with_source = {**agent, "source": source}
    storage.save_snapshot(agent_with_source, now)

    # Check for state changes
    prev_state = storage.update_agent_state(agent_with_source, now)
    if prev_state is not None:
        # State changed, check alerts
        alerter.check_and_alert(agent_with_source, prev_state)


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


async def cleanup_loop() -> None:
    """Periodic cleanup of old data."""
    while running:
        await asyncio.sleep(3600)  # Every hour
        try:
            deleted = storage.cleanup_old_data()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old records")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


async def context_monitor_loop(interval: int, threshold: float) -> None:
    """Periodic context usage monitoring."""
    logger.info(f"Context monitor started, interval={interval}s, threshold={threshold}%")
    while running:
        try:
            usages = context_monitor.get_all_context_usage()
            now = int(time.time())

            for usage in usages:
                # Save to database
                storage.save_context_usage(usage, now)

                # Check for alerts
                alerter.check_context_alert(
                    session_id=usage.session_id,
                    usage_percent=usage.usage_percent,
                    threshold=threshold,
                )

            if usages:
                high_usage = [u for u in usages if u.usage_percent > 50]
                if high_usage:
                    logger.info(f"Context usage: {len(usages)} sessions, {len(high_usage)} > 50%")

        except Exception as e:
            logger.error(f"Context monitor error: {e}")

        await asyncio.sleep(interval)


async def main_loop():
    """Main service loop."""
    global storage, collector, alerter, context_monitor, config, running

    logger.info("Agent Dashboard Service starting...")

    # Load config
    config = load_config()
    collector_cfg = config.get("collector", {})
    storage_cfg = config.get("storage", {})
    alerter_cfg = config.get("alerter", {})

    # Initialize storage (dashboard-specific + shared)
    storage = Storage(
        db_path=storage_cfg.get("database", "/xkagent_infra/runtime/data/services/dashboard.db"),
        shared_db_path=storage_cfg.get("shared_database", "/xkagent_infra/runtime/data/brain_shared.db"),
        retention_days=storage_cfg.get("retention_days", 7),
    )
    logger.info(f"Storage initialized: {storage.db_path} (shared: {storage.shared.db_path})")

    # Initialize alerter
    alerter = Alerter(
        storage=storage,
        daemon_socket=collector_cfg.get("daemon_socket", "/tmp/brain_ipc.sock"),
        target_agent=alerter_cfg.get("target_agent", "telegram"),
        cooldown_seconds=alerter_cfg.get("cooldown_seconds", 300),
        enabled=alerter_cfg.get("enabled", True),
    )
    logger.info(f"Alerter initialized, target={alerter.target_agent}")

    # Get tiered intervals from config
    intervals = collector_cfg.get("intervals", {
        "heartbeat": 10,
        "tmux_discovery": 30,
        "register": 60,
        "default": 30,
    })

    # Initialize collector with tiered intervals
    collector = Collector(
        daemon_socket=collector_cfg.get("daemon_socket", "/tmp/brain_ipc.sock"),
        intervals=intervals,
        on_agent_collected=on_agent_collected,
    )
    logger.info(f"Collector initialized, intervals={intervals}")

    # Check daemon connectivity and register via heartbeat
    if collector.is_daemon_alive():
        logger.info("Daemon connection OK")
        # Register by sending a startup message (triggers auto-heartbeat)
        if alerter.send_startup_notification():
            logger.info("Registered as IPC agent: service-dashboard")
        else:
            logger.warning("IPC registration via heartbeat failed")
    else:
        logger.warning("Daemon not reachable, will retry...")

    # Initialize context monitor
    context_cfg = config.get("context_monitor", {})
    context_monitor = ContextMonitor(
        projects_dir=context_cfg.get("projects_dir", "/root/.claude/projects/-brain"),
        context_window=context_cfg.get("context_window", 200000),
    )
    logger.info(f"Context monitor initialized, window={context_monitor.context_window}")

    # Start collector
    await collector.start()

    # Start cleanup task
    cleanup_task = asyncio.create_task(cleanup_loop())

    # Start context monitor task if enabled
    context_task = None
    if context_cfg.get("enabled", True):
        context_task = asyncio.create_task(context_monitor_loop(
            interval=context_cfg.get("interval_seconds", 60),
            threshold=context_cfg.get("alert_threshold_percent", 80),
        ))

    # Do initial collection of all agents
    initial_agents = collector.collect_all()
    logger.info(f"Initial discovery: {len(initial_agents)} agents")

    logger.info("Agent Dashboard Service running. Press Ctrl+C to stop.")

    # Main loop - just wait for shutdown
    try:
        while running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass

    # Shutdown
    logger.info("Shutting down...")
    cleanup_task.cancel()
    if context_task:
        context_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    if context_task:
        try:
            await context_task
        except asyncio.CancelledError:
            pass
    await collector.stop()
    logger.info("Agent Dashboard Service stopped")


def main():
    """Entry point."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run main loop
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
