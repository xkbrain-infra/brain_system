"""
BS-025-MOD-engine: Main Engine
asyncio 主循环，按序初始化各组件，统一协调 shutdown。

初始化顺序：ConfigLoader → StateStore → FSMEngine → Scheduler → IPCHandler
Shutdown 顺序：停 Scheduler → 停 IPCHandler → flush YAML → sys.exit(0)
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 环境变量 ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Engine:
    """
    task_manager_runtime 的主引擎。
    持有所有组件引用，负责启动、协调、优雅关闭。
    """

    def __init__(self):
        self._agent_name = _env("BRAIN_AGENT_NAME", "task_manager_runtime")
        self._projects_dir = _env("TMR_PROJECTS_DIR", "")
        self._state_dir = _env("TMR_STATE_DIR", "/brain/runtime/data/task_manager_runtime")
        self._health_port = int(_env("TMR_HEALTH_PORT", "8766"))

        # 组件引用
        self._config_loader = None
        self._runtime_state = None
        self._fsm_engine = None
        self._task_scheduler = None
        self._ipc_handler = None
        self._health_server = None

        # 项目配置缓存
        self._project_configs: List[Any] = []

        # shutdown 协调
        self._shutdown_event = asyncio.Event()
        self._fsm_lock = asyncio.Lock()
        self._started = False

    # ── 启动 ──────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        按序初始化各组件。
        任何组件初始化失败均记录错误并 sys.exit(1)。
        """
        logger.info(f"Engine starting: agent={self._agent_name}")

        try:
            await self._init_config_loader()
            await self._init_state_store()
            await self._init_fsm_engine()
            await self._init_scheduler()
            await self._init_ipc_handler()
            await self._init_health_server()
        except SystemExit:
            raise
        except Exception as e:
            logger.error(f"Engine startup failed: {e}", exc_info=True)
            sys.exit(1)

        self._register_signals()
        self._started = True
        logger.info("Engine started successfully, entering main loop")

    async def run(self) -> None:
        """启动所有组件并进入主循环，直到收到 shutdown 信号。"""
        await self.start()
        await self._main_loop()

    async def _main_loop(self) -> None:
        """等待 shutdown 信号，同时驱动 IPC 接收循环。"""
        ipc_task = asyncio.create_task(self._ipc_handler.start(), name="ipc_handler")
        shutdown_task = asyncio.create_task(
            self._shutdown_event.wait(), name="shutdown_wait"
        )

        done, pending = await asyncio.wait(
            [ipc_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 取消未完成的 task
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        await self._graceful_shutdown()

    # ── 组件初始化 ────────────────────────────────────────────────────────────

    async def _init_config_loader(self) -> None:
        from config_loader import ConfigLoader
        from state_store import cleanup_tmp_files

        if not self._projects_dir:
            logger.error("TMR_PROJECTS_DIR is not set")
            sys.exit(1)

        # 启动时清理 tmp 残留
        cleanup_tmp_files(self._projects_dir)

        self._config_loader = ConfigLoader(self._projects_dir)
        self._project_configs = self._config_loader.load_all()

        if not self._project_configs:
            logger.warning("No project configs loaded, engine will idle")

        logger.info(f"ConfigLoader initialized: {len(self._project_configs)} projects")

    async def _init_state_store(self) -> None:
        from state_store import RuntimeState

        os.makedirs(self._state_dir, exist_ok=True)
        runtime_json = os.path.join(self._state_dir, "runtime_state.json")
        self._runtime_state = RuntimeState(runtime_json)
        self._runtime_state.load()

        logger.info("StateStore initialized")

    async def _init_fsm_engine(self) -> None:
        from fsm import FSMEngine
        from ipc_sender import IPCSender

        self._ipc_sender = IPCSender(
            agent_name=self._agent_name,
            ipc_send_fn=self._ipc_send,
        )
        self._fsm_engine = FSMEngine()

        # 为每个项目的每个任务恢复 FSM 状态
        for cfg in self._project_configs:
            for task in cfg.tasks:
                task_id = task.get("id") or task.get("task_id", "")
                status = task.get("status", "pending")
                if not task_id or status in ("done", "cancelled", "failed"):
                    continue
                self._fsm_engine.get_or_create(
                    project_id=cfg.project_id,
                    task_id=task_id,
                    ipc_sender=self._ipc_sender,
                    state_store=self._make_state_store_adapter(cfg),
                    orchestrator_agent=cfg.orchestrator_agent,
                    qa_agent=cfg.qa_agent,
                    yaml_path=cfg.yaml_path,
                    initial_state=status,
                )

        logger.info("FSMEngine initialized")

    async def _init_scheduler(self) -> None:
        from scheduler import TaskScheduler

        self._task_scheduler = TaskScheduler()

        for cfg in self._project_configs:
            tasks_ref = cfg.tasks  # 引用，运行时动态读取

            def _get_tasks(tasks=tasks_ref):
                return tasks

            def _update_overdue(pid, tid, count, tasks=tasks_ref):
                for t in tasks:
                    if (t.get("id") or t.get("task_id")) == tid:
                        t["overdue_count"] = count
                        break

            self._task_scheduler.add_project(
                project_id=cfg.project_id,
                check_interval=cfg.check_interval,
                timeout_duration=cfg.timeout_duration,
                escalation_threshold=cfg.escalation_threshold,
                orchestrator_agent=cfg.orchestrator_agent,
                ipc_sender=self._ipc_sender,
                fsm_trigger=self._fsm_engine.trigger,
                get_tasks_fn=_get_tasks,
                update_overdue_fn=_update_overdue,
            )

        self._task_scheduler.start()
        logger.info("Scheduler initialized and started")

    async def _init_ipc_handler(self) -> None:
        from ipc_handler import IPCHandler

        self._ipc_handler = IPCHandler(
            ipc_recv_fn=self._ipc_recv,
            fsm_trigger=self._fsm_engine.trigger,
            runtime_state=self._runtime_state,
        )
        logger.info("IPCHandler initialized")

    async def _init_health_server(self) -> None:
        # health.py 由 T9 实现，此处 gracefully skip
        try:
            from health import HealthServer
            self._health_server = HealthServer(
                port=self._health_port,
                engine=self,
            )
            asyncio.create_task(self._health_server.start(), name="health_server")
            logger.info(f"HealthServer initialized on port {self._health_port}")
        except ImportError:
            logger.info("health.py not available, skipping health server")

    # ── 信号处理 ──────────────────────────────────────────────────────────────

    def _register_signals(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self._handle_signal(s))
            )
        logger.info("Signal handlers registered (SIGTERM, SIGINT)")

    async def _handle_signal(self, sig: signal.Signals) -> None:
        logger.info(f"Received signal {sig.name}, initiating graceful shutdown")
        self._ipc_handler.stop()
        self._shutdown_event.set()

    # ── Graceful Shutdown ─────────────────────────────────────────────────────

    async def _graceful_shutdown(self) -> None:
        """
        关闭顺序：
        1. 停止 Scheduler（不再触发新扫描）
        2. 等待当前 FSM transition 完成（通过 _fsm_lock，最多 5s）
        3. flush 所有项目状态到 YAML
        4. 更新 runtime_state.json（last_shutdown_time）
        5. sys.exit(0)
        """
        from datetime import datetime, timezone

        logger.info("Graceful shutdown initiated")

        # Step 1: 停止 Scheduler
        if self._task_scheduler:
            self._task_scheduler.stop()
            logger.info("Scheduler stopped")

        # Step 2: 等待 FSM lock（最多 5s）
        try:
            await asyncio.wait_for(self._fsm_lock.acquire(), timeout=5.0)
            self._fsm_lock.release()
        except asyncio.TimeoutError:
            logger.warning("FSM lock timeout during shutdown, proceeding anyway")

        # Step 3: flush 所有项目 YAML
        if self._config_loader and self._project_configs:
            from state_store import read_project_state, write_project_state
            for cfg in self._project_configs:
                data = read_project_state(cfg.yaml_path)
                if data is None:
                    continue
                # 将内存中的 FSM 状态同步回 yaml data
                models = self._fsm_engine.all_models() if self._fsm_engine else {}
                tasks_raw = data.get("tasks", {})
                for (pid, tid), model in models.items():
                    if pid != cfg.project_id:
                        continue
                    if isinstance(tasks_raw, dict) and tid in tasks_raw:
                        tasks_raw[tid]["status"] = model.state
                    elif isinstance(tasks_raw, list):
                        for t in tasks_raw:
                            if (t.get("id") or t.get("task_id")) == tid:
                                t["status"] = model.state
                write_project_state(cfg.yaml_path, data)
                logger.info(f"Flushed state: {cfg.yaml_path}")

        # Step 4: 更新 runtime_state.json
        if self._runtime_state:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._runtime_state.set_last_shutdown_time(now_iso)
            self._runtime_state.save()
            logger.info("Runtime state saved")

        logger.info("Graceful shutdown complete, exiting")
        sys.exit(0)

    # ── IPC 适配器（占位，运行时由 MCP 工具替换）────────────────────────────

    def _ipc_send(self, **kwargs) -> Dict[str, Any]:
        """占位：实际运行时由注入的 MCP ipc_send 函数替换。"""
        raise NotImplementedError("ipc_send_fn not injected")

    def _ipc_recv(self, **kwargs) -> Dict[str, Any]:
        """占位：实际运行时由注入的 MCP ipc_recv 函数替换。"""
        raise NotImplementedError("ipc_recv_fn not injected")

    def inject_ipc(self, send_fn, recv_fn) -> None:
        """注入实际的 MCP IPC 函数（测试或运行时调用）。"""
        self._ipc_send = send_fn
        self._ipc_recv = recv_fn
        # 同步更新已创建的 IPCSender
        if hasattr(self, "_ipc_sender"):
            self._ipc_sender._ipc_send_fn = send_fn

    # ── StateStore 适配器 ─────────────────────────────────────────────────────

    def _make_state_store_adapter(self, cfg) -> Any:
        """为 TaskModel._persist 提供一个简单适配器。"""

        class _Adapter:
            def update_task(self_, model) -> None:
                from state_store import read_project_state, write_project_state
                data = read_project_state(cfg.yaml_path)
                if data is None:
                    return
                tasks_raw = data.get("tasks", {})
                if isinstance(tasks_raw, dict):
                    if model.task_id in tasks_raw:
                        tasks_raw[model.task_id]["status"] = model.state
                        if model.start_time:
                            tasks_raw[model.task_id]["start_time"] = model.start_time
                        tasks_raw[model.task_id]["overdue_count"] = model.overdue_count
                elif isinstance(tasks_raw, list):
                    for t in tasks_raw:
                        if (t.get("id") or t.get("task_id")) == model.task_id:
                            t["status"] = model.state
                            if model.start_time:
                                t["start_time"] = model.start_time
                            t["overdue_count"] = model.overdue_count
                write_project_state(cfg.yaml_path, data)

        return _Adapter()

    # ── 健康检查指标（供 health.py 读取）────────────────────────────────────

    @property
    def managed_projects(self) -> int:
        return len(self._project_configs)

    @property
    def active_tasks(self) -> int:
        if not self._fsm_engine:
            return 0
        return sum(
            1 for m in self._fsm_engine.all_models().values()
            if m.state not in ("done", "cancelled", "failed")
        )

    @property
    def scheduler_running(self) -> bool:
        return bool(self._task_scheduler and self._task_scheduler.running)
