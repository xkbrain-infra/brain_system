"""
BS-025-MOD-fsm: FSM Engine
使用 transitions.extensions.asyncio.AsyncMachine 管理任务状态机。
每个 (project_id, task_id) 对应一个独立的 TaskModel 实例。
queued='model' 保证同一任务的并发事件被序列化处理。
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from transitions.extensions.asyncio import AsyncMachine

logger = logging.getLogger(__name__)

# ── 状态定义 ──────────────────────────────────────────────────────────────────

STATES = [
    "pending",      # 任务已创建，等待分配
    "assigned",     # 已分配给 agent，等待开始
    "in_progress",  # agent 工作中
    "reviewing",    # 提交完成，等待 QA 评审
    "revision",     # QA 要求修改，等待 agent 修改
    "blocked",      # 被外部依赖或问题阻塞
    "done",         # QA 通过，完成（终态）
    "failed",       # 超出重试，失败（终态）
    "cancelled",    # 取消（终态）
]

# ── 转换规则 ──────────────────────────────────────────────────────────────────

TRANSITIONS = [
    # trigger            source(s)                          dest
    {"trigger": "assign",           "source": "pending",                         "dest": "assigned"},
    {"trigger": "start",            "source": "assigned",                        "dest": "in_progress"},
    {"trigger": "submit",           "source": "in_progress",                     "dest": "reviewing"},
    {"trigger": "approve",          "source": "reviewing",                       "dest": "done"},
    {"trigger": "request_revision", "source": "reviewing",                       "dest": "revision"},
    {"trigger": "resubmit",         "source": "revision",                        "dest": "in_progress"},
    {"trigger": "block",            "source": ["in_progress", "assigned"],       "dest": "blocked"},
    {"trigger": "unblock",          "source": "blocked",                         "dest": "in_progress"},
    {"trigger": "fail",             "source": ["in_progress", "assigned",
                                               "blocked"],                        "dest": "failed"},
    {"trigger": "retry",            "source": "failed",                          "dest": "pending"},
    {"trigger": "cancel",           "source": ["pending", "assigned",
                                               "in_progress", "blocked",
                                               "revision"],                       "dest": "cancelled"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Task Model ────────────────────────────────────────────────────────────────

class TaskModel:
    """
    单个任务的状态机模型。
    AsyncMachine 会将 trigger 方法注入到实例上（assign/start/submit 等）。
    on_enter_* callback 在进入新状态时被调用，负责：
      1. 更新内存中的任务元数据（assigned_to, start_time 等）
      2. 通过 IPCSender 发送 IPC 通知
      3. 通过 StateStore 持久化状态
    """

    def __init__(
        self,
        project_id: str,
        task_id: str,
        ipc_sender,       # IPCSender 实例
        state_store,      # 提供 write_project_state 的 StateStore 封装
        orchestrator_agent: str,
        qa_agent: Optional[str],
        yaml_path: str,
        initial_state: str = "pending",
    ):
        self.project_id = project_id
        self.task_id = task_id
        self._ipc_sender = ipc_sender
        self._state_store = state_store
        self._orchestrator_agent = orchestrator_agent
        self._qa_agent = qa_agent
        self._yaml_path = yaml_path

        # 运行时元数据（与 YAML 中 task 字段对应）
        self.assigned_to: Optional[str] = None
        self.start_time: Optional[str] = None
        self.overdue_count: int = 0
        self.block_reason: Optional[str] = None

        # AsyncMachine 初始化（在 FSMEngine 中统一完成，此处仅占位）
        self.state: str = initial_state

    # ── on_enter callbacks ────────────────────────────────────────────────────

    async def on_enter_assigned(self) -> None:
        logger.info(f"[{self.project_id}/{self.task_id}] → assigned (agent={self.assigned_to})")
        await self._persist()
        if self.assigned_to and self._ipc_sender:
            await self._ipc_sender.send_task_assigned(
                to=self.assigned_to,
                project_id=self.project_id,
                task_id=self.task_id,
                task_title=self.task_id,
                task_description="",
                assigned_agent=self.assigned_to,
            )

    async def on_enter_in_progress(self) -> None:
        if not self.start_time:
            self.start_time = _now_iso()
        self.overdue_count = 0
        logger.info(f"[{self.project_id}/{self.task_id}] → in_progress")
        await self._persist()

    async def on_enter_reviewing(self) -> None:
        logger.info(f"[{self.project_id}/{self.task_id}] → reviewing")
        await self._persist()
        if self._qa_agent and self._ipc_sender:
            await self._ipc_sender.send_task_review_ready(
                to=self._qa_agent,
                project_id=self.project_id,
                task_id=self.task_id,
                submitted_by=self.assigned_to or "unknown",
            )

    async def on_enter_done(self) -> None:
        logger.info(f"[{self.project_id}/{self.task_id}] → done ✓")
        await self._persist()

    async def on_enter_revision(self) -> None:
        logger.info(f"[{self.project_id}/{self.task_id}] → revision")
        await self._persist()
        if self.assigned_to and self._ipc_sender:
            await self._ipc_sender.send_message(
                to=self.assigned_to,
                event_type="TASK_REVISION_REQUESTED",
                payload={"project_id": self.project_id, "task_id": self.task_id},
            )

    async def on_enter_blocked(self) -> None:
        logger.info(
            f"[{self.project_id}/{self.task_id}] → blocked "
            f"(reason={self.block_reason})"
        )
        await self._persist()
        if self._ipc_sender:
            await self._ipc_sender.send_message(
                to=self._orchestrator_agent,
                event_type="TASK_BLOCKED",
                payload={
                    "project_id": self.project_id,
                    "task_id": self.task_id,
                    "assigned_agent": self.assigned_to or "",
                    "reason": self.block_reason or "",
                },
            )

    async def on_enter_failed(self) -> None:
        logger.warning(f"[{self.project_id}/{self.task_id}] → failed")
        await self._persist()

    async def on_enter_cancelled(self) -> None:
        logger.info(f"[{self.project_id}/{self.task_id}] → cancelled")
        await self._persist()

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """将当前状态更新到 StateStore（非阻塞，失败仅记录日志）。"""
        if self._state_store is None:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._state_store.update_task, self
            )
        except Exception as e:
            logger.error(
                f"[{self.project_id}/{self.task_id}] persist failed: {e}"
            )


# ── FSM Engine ────────────────────────────────────────────────────────────────

class FSMEngine:
    """
    管理所有项目所有任务的 AsyncMachine 实例。
    提供按 (project_id, task_id) 查找、创建、触发 FSM 的统一接口。
    """

    def __init__(self):
        # (project_id, task_id) -> TaskModel
        self._models: Dict[Tuple[str, str], TaskModel] = {}

    def create_task(
        self,
        project_id: str,
        task_id: str,
        ipc_sender,
        state_store,
        orchestrator_agent: str,
        qa_agent: Optional[str],
        yaml_path: str,
        initial_state: str = "pending",
    ) -> TaskModel:
        """创建并注册一个新的 TaskModel，返回已绑定 AsyncMachine 的实例。"""
        model = TaskModel(
            project_id=project_id,
            task_id=task_id,
            ipc_sender=ipc_sender,
            state_store=state_store,
            orchestrator_agent=orchestrator_agent,
            qa_agent=qa_agent,
            yaml_path=yaml_path,
            initial_state=initial_state,
        )
        # 为每个模型独立构建 AsyncMachine
        # queued='model' 保证同一模型的并发 trigger 被序列化
        AsyncMachine(
            model=model,
            states=STATES,
            transitions=TRANSITIONS,
            initial=initial_state,
            queued="model",
            ignore_invalid_triggers=False,
            auto_transitions=False,
        )
        key = (project_id, task_id)
        self._models[key] = model
        logger.debug(f"FSM created: {project_id}/{task_id} state={initial_state}")
        return model

    def get_task(self, project_id: str, task_id: str) -> Optional[TaskModel]:
        return self._models.get((project_id, task_id))

    def get_or_create(
        self,
        project_id: str,
        task_id: str,
        ipc_sender,
        state_store,
        orchestrator_agent: str,
        qa_agent: Optional[str],
        yaml_path: str,
        initial_state: str = "pending",
    ) -> TaskModel:
        model = self.get_task(project_id, task_id)
        if model is None:
            model = self.create_task(
                project_id, task_id, ipc_sender, state_store,
                orchestrator_agent, qa_agent, yaml_path, initial_state,
            )
        return model

    async def trigger(
        self,
        project_id: str,
        task_id: str,
        trigger_name: str,
        **kwargs: Any,
    ) -> bool:
        """
        触发指定任务的 FSM 事件。
        kwargs 中的字段会在触发前注入到 model（如 assigned_to, block_reason）。
        非法转换返回 False（MachineError 被捕获后记录日志）。
        """
        model = self.get_task(project_id, task_id)
        if model is None:
            logger.warning(
                f"FSM trigger '{trigger_name}' on unknown task "
                f"{project_id}/{task_id}"
            )
            return False

        # 将附加参数注入到 model 属性（用于 callback 中使用）
        for k, v in kwargs.items():
            setattr(model, k, v)

        trigger_fn = getattr(model, trigger_name, None)
        if trigger_fn is None:
            logger.error(f"Unknown trigger '{trigger_name}'")
            return False

        try:
            await trigger_fn()
            return True
        except Exception as e:
            logger.warning(
                f"FSM trigger '{trigger_name}' rejected for "
                f"{project_id}/{task_id} (state={model.state}): {e}"
            )
            return False

    def all_models(self) -> Dict[Tuple[str, str], TaskModel]:
        return dict(self._models)

    def remove_task(self, project_id: str, task_id: str) -> None:
        self._models.pop((project_id, task_id), None)
