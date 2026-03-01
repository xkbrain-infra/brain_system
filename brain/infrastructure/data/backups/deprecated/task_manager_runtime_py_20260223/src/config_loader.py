"""
BS-025-MOD-config-loader: Config Loader
加载 task_manager.yaml v2，schema 校验，mtime 热更新检测
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

REQUIRED_TOP_FIELDS = ["project_id", "runtime", "agent_roster", "tasks"]
REQUIRED_RUNTIME_FIELDS = ["check_interval", "timeout_duration", "orchestrator_agent"]


@dataclass
class AgentRosterEntry:
    agent_name: str
    role: str
    max_concurrent_tasks: int = 1


@dataclass
class ProjectConfig:
    project_id: str
    yaml_path: str
    check_interval: int           # seconds
    timeout_duration: int         # seconds
    escalation_threshold: int
    qa_agent: Optional[str]
    orchestrator_agent: str
    agent_roster: List[AgentRosterEntry]
    tasks: List[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)


class ConfigLoader:
    """
    扫描目录下所有 task_manager.yaml，加载并缓存，支持 mtime 热更新。
    格式错误的 YAML 被跳过，不影响其他项目加载。
    """

    def __init__(self, projects_dir: str):
        self.projects_dir = projects_dir
        # yaml_path -> (mtime, ProjectConfig)
        self._cache: Dict[str, tuple] = {}

    def load_all(self) -> List[ProjectConfig]:
        """扫描 projects_dir，加载所有 task_manager.yaml，返回有效 ProjectConfig 列表。"""
        configs: List[ProjectConfig] = []
        if not os.path.isdir(self.projects_dir):
            logger.warning(f"Projects dir not found: {self.projects_dir}")
            return configs

        for entry in os.scandir(self.projects_dir):
            if not entry.is_dir():
                continue
            yaml_path = os.path.join(entry.path, "task_manager.yaml")
            if not os.path.isfile(yaml_path):
                continue
            cfg = self._load_single(yaml_path)
            if cfg is not None:
                configs.append(cfg)

        logger.info(f"Loaded {len(configs)} project configs from {self.projects_dir}")
        return configs

    def load_from_path(self, yaml_path: str) -> Optional[ProjectConfig]:
        """加载单个指定路径的 yaml。"""
        return self._load_single(yaml_path)

    def check_hot_reload(self) -> List[ProjectConfig]:
        """
        检查已加载的 yaml 是否有 mtime 变化，重新加载变更的文件。
        返回更新后的全量 ProjectConfig 列表。
        """
        for yaml_path, (cached_mtime, _) in list(self._cache.items()):
            try:
                current_mtime = os.path.getmtime(yaml_path)
            except OSError:
                logger.warning(f"Cannot stat {yaml_path}, removing from cache")
                del self._cache[yaml_path]
                continue

            if current_mtime != cached_mtime:
                logger.info(f"Hot reload triggered: {yaml_path} mtime changed")
                self._load_single(yaml_path)

        return [cfg for (_, cfg) in self._cache.values()]

    def _load_single(self, yaml_path: str) -> Optional[ProjectConfig]:
        """加载并校验单个 yaml，成功则更新缓存，失败返回 None。"""
        try:
            mtime = os.path.getmtime(yaml_path)
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.warning(f"YAML parse error in {yaml_path}: {e}, skipping")
            return None
        except OSError as e:
            logger.warning(f"Cannot read {yaml_path}: {e}, skipping")
            return None

        cfg = self._validate_and_build(yaml_path, data)
        if cfg is None:
            return None

        self._cache[yaml_path] = (mtime, cfg)
        return cfg

    def _validate_and_build(self, yaml_path: str, data: Any) -> Optional[ProjectConfig]:
        """校验 schema 并构建 ProjectConfig，失败返回 None。"""
        if not isinstance(data, dict):
            logger.warning(f"Invalid YAML (not a dict) in {yaml_path}, skipping")
            return None

        for fname in REQUIRED_TOP_FIELDS:
            if fname not in data:
                logger.warning(f"Missing required field '{fname}' in {yaml_path}, skipping")
                return None

        runtime = data.get("runtime", {})
        if not isinstance(runtime, dict):
            logger.warning(f"'runtime' must be a dict in {yaml_path}, skipping")
            return None

        for rf in REQUIRED_RUNTIME_FIELDS:
            if rf not in runtime:
                logger.warning(f"Missing runtime field '{rf}' in {yaml_path}, skipping")
                return None

        # 解析 agent_roster
        roster: List[AgentRosterEntry] = []
        for entry in data.get("agent_roster", []):
            if not isinstance(entry, dict) or "agent_name" not in entry:
                continue
            roster.append(AgentRosterEntry(
                agent_name=entry["agent_name"],
                role=entry.get("role", "developer"),
                max_concurrent_tasks=int(entry.get("max_concurrent_tasks", 1)),
            ))

        # 解析 tasks（兼容 dict 格式 v1 和 list 格式 v2）
        tasks_raw = data.get("tasks", [])
        if isinstance(tasks_raw, dict):
            tasks = [{"id": k, **v} for k, v in tasks_raw.items()]
        elif isinstance(tasks_raw, list):
            tasks = tasks_raw
        else:
            tasks = []

        return ProjectConfig(
            project_id=data["project_id"],
            yaml_path=yaml_path,
            check_interval=int(runtime.get("check_interval", 60)),
            timeout_duration=int(runtime.get("timeout_duration", 3600)),
            escalation_threshold=int(runtime.get("escalation_threshold", 2)),
            qa_agent=runtime.get("qa_agent"),
            orchestrator_agent=runtime["orchestrator_agent"],
            agent_roster=roster,
            tasks=tasks,
            raw=data,
        )
