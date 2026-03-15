"""
BS-025-MOD-scheduler: Scheduler
APScheduler 3.x AsyncIOScheduler 定时扫描 + 超时检测。
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


class TaskScanContext:
    """单次扫描中对一个项目的 task 检查上下文。"""

    def __init__(
        self,
        project_id: str,
        timeout_duration: int,       # seconds
        escalation_threshold: int,
        orchestrator_agent: str,
        ipc_sender,
        fsm_trigger: Callable,
        state_store_get_tasks: Callable,  # () -> List[dict]
        state_store_update_overdue: Callable,  # (project_id, task_id, overdue_count) -> None
    ):
        self.project_id = project_id
        self.timeout_duration = timeout_duration
        self.escalation_threshold = escalation_threshold
        self.orchestrator_agent = orchestrator_agent
        self.ipc_sender = ipc_sender
        self.fsm_trigger = fsm_trigger
        self._get_tasks = state_store_get_tasks
        self._update_overdue = state_store_update_overdue

    async def scan(self) -> None:
        """扫描该项目的所有 active 任务，检测超时。"""
        now = _now()
        tasks = self._get_tasks()

        for task in tasks:
            status = task.get("status", "")
            if status not in ("assigned", "in_progress"):
                continue

            task_id = task.get("id") or task.get("task_id", "")
            if not task_id:
                continue

            start_time = _parse_iso(task.get("start_time"))
            if start_time is None:
                continue

            # 确保时区统一
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            elapsed = (now - start_time).total_seconds()
            if elapsed <= self.timeout_duration:
                continue

            # 超时处理
            overdue_count = int(task.get("overdue_count", 0)) + 1
            overdue_minutes = int(elapsed // 60)
            assigned_agent = task.get("assigned_to", "")

            logger.warning(
                f"[{self.project_id}/{task_id}] overdue #{overdue_count}, "
                f"{overdue_minutes}min elapsed"
            )

            # 更新内存中的 overdue_count
            self._update_overdue(self.project_id, task_id, overdue_count)

            # 发送 TASK_OVERDUE 通知
            if self.ipc_sender:
                await self.ipc_sender.send_task_overdue(
                    to=self.orchestrator_agent,
                    project_id=self.project_id,
                    task_id=task_id,
                    assigned_agent=assigned_agent,
                    overdue_minutes=overdue_minutes,
                    overdue_count=overdue_count,
                )

            # 连续超时达阈值 → 触发 FSM block
            if overdue_count >= self.escalation_threshold:
                logger.warning(
                    f"[{self.project_id}/{task_id}] escalating to blocked "
                    f"(overdue_count={overdue_count} >= threshold={self.escalation_threshold})"
                )
                if self.fsm_trigger:
                    await self.fsm_trigger(
                        self.project_id, task_id, "block",
                        block_reason=f"overdue {overdue_count} times"
                    )


class ProjectScheduler:
    """为单个项目维护一个 APScheduler interval job。"""

    def __init__(
        self,
        project_id: str,
        check_interval: int,
        scan_fn: Callable,           # async () -> None
        scheduler: AsyncIOScheduler,
    ):
        self.project_id = project_id
        self.check_interval = check_interval
        self._scan_fn = scan_fn
        self._scheduler = scheduler
        self._job_id = f"scan_{project_id}"

    def start(self) -> None:
        self._scheduler.add_job(
            self._scan_fn,
            trigger="interval",
            seconds=self.check_interval,
            id=self._job_id,
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=self.check_interval,
        )
        logger.info(
            f"Scheduler job registered: {self._job_id} "
            f"interval={self.check_interval}s"
        )

    def stop(self) -> None:
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)


class TaskScheduler:
    """
    管理所有项目的 APScheduler AsyncIOScheduler。
    每个项目独立的 interval job，互不干扰。
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._project_schedulers: Dict[str, ProjectScheduler] = {}

    def add_project(
        self,
        project_id: str,
        check_interval: int,
        timeout_duration: int,
        escalation_threshold: int,
        orchestrator_agent: str,
        ipc_sender,
        fsm_trigger: Callable,
        get_tasks_fn: Callable,
        update_overdue_fn: Callable,
    ) -> None:
        """注册一个项目的定时扫描 job。"""
        ctx = TaskScanContext(
            project_id=project_id,
            timeout_duration=timeout_duration,
            escalation_threshold=escalation_threshold,
            orchestrator_agent=orchestrator_agent,
            ipc_sender=ipc_sender,
            fsm_trigger=fsm_trigger,
            state_store_get_tasks=get_tasks_fn,
            state_store_update_overdue=update_overdue_fn,
        )
        ps = ProjectScheduler(
            project_id=project_id,
            check_interval=check_interval,
            scan_fn=ctx.scan,
            scheduler=self._scheduler,
        )
        self._project_schedulers[project_id] = ps

        if self._scheduler.running:
            ps.start()

    def start(self) -> None:
        """启动 AsyncIOScheduler 并注册所有已添加的项目 job。"""
        self._scheduler.start()
        for ps in self._project_schedulers.values():
            ps.start()
        logger.info(
            f"TaskScheduler started with {len(self._project_schedulers)} projects"
        )

    def stop(self) -> None:
        """停止所有 job 并关闭 Scheduler。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("TaskScheduler stopped")

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def remove_project(self, project_id: str) -> None:
        ps = self._project_schedulers.pop(project_id, None)
        if ps:
            ps.stop()
