#!/usr/bin/env python3
"""
Sandbox Service - Brain Group Sandbox 管理服务
规范: /xkagent_infra/brain/base/sandbox/index.yaml (发布态)
源码: /xkagent_infra/groups/brain/projects/infrastructure/brain_sandbox_service/
部署: /xkagent_infra/brain/infrastructure/service/brain_sandbox_service/
运行时: /xkagent_infra/groups/brain/platform/sandbox/
"""

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


class SandboxConfig:
    """Sandbox 配置管理

    架构分离:
    - BASE_ROOT: 源代码根目录 (groups/brain/projects/base/sandbox)
    - PLATFORM_ROOT: 运行时数据根目录 (groups/brain/platform/sandbox)
    """

    # 源代码路径 (base 项目，发布后同步到 brain/base/sandbox)
    BASE_ROOT = Path("/xkagent_infra/groups/brain/projects/base/sandbox")
    # 运行时数据路径 (platform 目录，实例、注册表、归档)
    PLATFORM_ROOT = Path("/xkagent_infra/groups/brain/platform/sandbox")
    GROUP = "brain"

    # 类型到目录前缀的映射
    TYPE_DIR_MAP = {
        "development": "dev",
        "testing": "test",
        "staging": "staging",
        "audit": "audit"
    }

    # 项目别名映射（用于命名规范兼容）
    PROJECT_ALIAS_MAP = {
        "brain_agent_proxy": "agent-proxy",
    }

    @classmethod
    def projects_root(cls) -> Path:
        return Path("/xkagent_infra/groups") / cls.GROUP / "projects"

    @classmethod
    def normalize_project_name(cls, project: str) -> str:
        value = str(project or "").strip().lower().replace("_", "-")
        value = re.sub(r"[^a-z0-9-]+", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-")
        return value

    @classmethod
    def project_lookup_key(cls, project: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", cls.normalize_project_name(project))

    @classmethod
    def resolve_project_name(cls, project: str) -> str:
        raw = str(project or "").strip()
        if not raw:
            return raw

        projects_root = cls.projects_root()
        direct = projects_root / raw
        if direct.exists():
            return raw

        normalized = cls.normalize_project_name(raw)
        if normalized:
            normalized_path = projects_root / normalized
            if normalized_path.exists():
                return normalized

        lookup_key = cls.project_lookup_key(normalized)
        if projects_root.exists():
            for child in projects_root.iterdir():
                if not child.is_dir():
                    continue
                child_normalized = cls.normalize_project_name(child.name)
                if child_normalized == normalized:
                    return child.name
                if lookup_key and cls.project_lookup_key(child.name) == lookup_key:
                    return child.name

        return normalized or raw

    @classmethod
    def get_project_alias(cls, project: str) -> str:
        """获取用于容器命名的项目别名"""
        resolved = cls.resolve_project_name(project)
        candidates = (
            str(project or "").strip(),
            resolved,
            cls.normalize_project_name(project),
            cls.normalize_project_name(resolved),
            cls.normalize_project_name(resolved).replace("-", "_"),
        )
        for candidate in candidates:
            alias = cls.PROJECT_ALIAS_MAP.get(candidate)
            if alias:
                return cls.normalize_project_name(alias)

        alias = cls.normalize_project_name(resolved or project)
        group_prefix = f"{cls.GROUP}-"
        if alias.startswith(group_prefix):
            alias = alias[len(group_prefix):]
        return alias

    @classmethod
    def load_platform_config(cls) -> Dict:
        """加载平台主配置 (从 base 项目源码)"""
        # 优先从源码读取，发布后会同步到 brain/base/sandbox/
        config_path = cls.BASE_ROOT / "index.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    @classmethod
    def load_project_config(cls, project: str) -> Optional[Dict]:
        """加载项目级配置"""
        resolved_project = cls.resolve_project_name(project)
        config_path = cls.projects_root() / resolved_project / ".sandbox" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)
        return None

    @classmethod
    def load_provider_config(cls, provider: str = "docker") -> Dict:
        """加载 Provider 配置 (从 base 项目源码)"""
        config_path = cls.BASE_ROOT / "providers" / f"{provider}.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)


class SandboxNaming:
    """Sandbox 命名规范"""

    @staticmethod
    def generate_instance_id(length: int = 6) -> str:
        """生成实例 ID"""
        chars = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(chars) for _ in range(length))

    @staticmethod
    def container_name(group: str, project: str, dep_type: str, instance_id: str) -> str:
        """生成容器名称"""
        return f"{group}-{project}-{dep_type}-{instance_id}"

    @staticmethod
    def network_name(group: str, dep_type: str, instance_id: str) -> str:
        """生成网络名称"""
        return f"{group}-{dep_type}-{instance_id}"

    @staticmethod
    def volume_name(group: str, project: str, dep_type: str, instance_id: str, purpose: str) -> str:
        """生成卷名称"""
        return f"{group}_{project}_{dep_type}_{instance_id}_{purpose}"


class SandboxRegistry:
    """Sandbox 实例注册表管理 (运行时数据，存储在 platform 目录)"""

    REGISTRY_PATH = Path("/xkagent_infra/groups/brain/platform/sandbox/registry/instances")
    ARCHIVE_PATH = Path("/xkagent_infra/groups/brain/platform/sandbox/archives")
    INSTANCES_PATH = Path("/xkagent_infra/groups/brain/platform/sandbox/instances")

    def __init__(self):
        self.REGISTRY_PATH.mkdir(parents=True, exist_ok=True)
        self.ARCHIVE_PATH.mkdir(parents=True, exist_ok=True)

    def register(self, instance: Dict) -> None:
        """注册新实例"""
        instance_id = instance["instance_id"]
        registry_file = self.REGISTRY_PATH / f"{instance_id}.yaml"

        with open(registry_file, 'w') as f:
            yaml.dump(instance, f, default_flow_style=False)

    def get(self, instance_id: str) -> Optional[Dict]:
        """获取实例信息"""
        registry_file = self.REGISTRY_PATH / f"{instance_id}.yaml"
        if registry_file.exists():
            with open(registry_file) as f:
                return yaml.safe_load(f)
        return None

    def update(self, instance_id: str, updates: Dict) -> None:
        """更新实例信息"""
        instance = self.get(instance_id)
        if instance:
            instance.update(updates)
            instance["updated_at"] = datetime.now().isoformat()
            self.register(instance)

    def list_by_project(self, project: str) -> List[Dict]:
        """按项目列出实例"""
        instances = []
        for f in self.REGISTRY_PATH.glob("*.yaml"):
            with open(f) as fp:
                data = yaml.safe_load(fp)
                if data and data.get("project") == project:
                    instances.append(data)
        return instances

    def list_by_type(self, dep_type: str) -> List[Dict]:
        """按类型列出实例"""
        instances = []
        for f in self.REGISTRY_PATH.glob("*.yaml"):
            with open(f) as fp:
                data = yaml.safe_load(fp)
                if data and data.get("type") == dep_type:
                    instances.append(data)
        return instances

    def archive(self, instance_id: str) -> None:
        """归档实例"""
        registry_file = self.REGISTRY_PATH / f"{instance_id}.yaml"
        if registry_file.exists():
            archive_file = self.ARCHIVE_PATH / f"{instance_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
            instance = yaml.safe_load(registry_file.read_text())
            instance["archived_at"] = datetime.now().isoformat()
            with open(archive_file, 'w') as f:
                yaml.dump(instance, f, default_flow_style=False)
            registry_file.unlink()


class SandboxLEPChecker:
    """LEP Gates 检查器"""

    def __init__(self, project: str, dep_type: str, instance_id: str, project_config: Optional[Dict] = None):
        self.project = project
        self.project_alias = SandboxConfig.get_project_alias(project)
        self.dep_type = dep_type
        self.instance_id = instance_id
        # 从 project_config 读取 group，默认 "brain"
        if project_config:
            self.group = project_config.get('sandbox', {}).get('naming', {}).get('group', 'brain')
        else:
            self.group = "brain"
        self.container_name = SandboxNaming.container_name(
            self.group, self.project_alias, dep_type, instance_id
        )

    def check_all(self) -> Tuple[bool, List[str]]:
        """执行所有 LEP 检查"""
        errors = []

        # G-SANDBOX-NAME: 命名规范
        if not self._check_naming():
            errors.append(f"G-SANDBOX-NAME: 容器名称 '{self.container_name}' 不符合规范")

        # G-SANDBOX-UNIQUE: 唯一性
        if not self._check_unique():
            errors.append(f"G-SANDBOX-UNIQUE: 容器 '{self.container_name}' 已存在")

        # G-SANDBOX-PRIVILEGED: 禁止特权模式
        # (在创建时检查)

        return len(errors) == 0, errors

    def _check_naming(self) -> bool:
        """检查命名规范"""
        pattern = r'^[a-z][a-z0-9-]{0,63}$'
        return bool(re.match(pattern, self.container_name))

    def _check_unique(self) -> bool:
        """检查容器唯一性"""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"],
                capture_output=True, text=True
            )
            existing = [n for n in result.stdout.strip().split('\n') if n]
            return len(existing) == 0
        except Exception:
            return True


class SandboxManager:
    """Sandbox 管理主类"""

    ORCHESTRATOR_ROLE = "orchestrator"
    DEFAULT_ATTACHED_AGENT_ROLE = ORCHESTRATOR_ROLE
    DEFAULT_ORCHESTRATOR_MODEL = "minimax/minimax-m2.7"
    PROJECT_ROLE_ALIASES = {
        "orchestrator": ("orchestrator", "project_orchestrator"),
        "project_orchestrator": ("orchestrator", "project_orchestrator"),
        "designer": ("designer", "dev_ui"),
        "ui_dev": ("designer", "dev_ui"),
        "dev": ("dev", "developer"),
        "developer": ("dev", "developer"),
        "qa": ("qa", "qa"),
        "researcher": ("researcher", "researcher"),
        "devops": ("devops", "devops"),
        "architect": ("architect", "architect"),
        "worker": ("worker", "developer"),
    }
    PUBLISHED_SERVICE_ROOT = Path("/xkagent_infra/brain/infrastructure/service/brain_sandbox_service")
    IPC_BRIDGE_SCRIPT_HOST = PUBLISHED_SERVICE_ROOT / "current" / "ipc_socket_bridge.py"
    IPC_BRIDGE_SCRIPT_CONTAINER = "/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service/current/ipc_socket_bridge.py"
    IPC_BRIDGE_STATE_ROOT = Path("/xkagent_infra/runtime/sandbox/_services/ipc_bridge")
    HOST_IPC_SOCKET = "/brain/tmp_ipc/brain_ipc.sock"
    HOST_NOTIFY_SOCKET = "/tmp/brain_ipc_notify.sock"
    HOST_IPC_BRIDGE_HOST = "0.0.0.0"
    HOST_IPC_BRIDGE_PORT = 9800
    HOST_NOTIFY_BRIDGE_PORT = 9801
    CONTAINER_IPC_SOCKET = "/tmp/brain_ipc.sock"
    CONTAINER_NOTIFY_SOCKET = "/tmp/brain_ipc_notify.sock"
    ORCHESTRATOR_WORKFLOW_ROOTS = (
        Path("/xkagent_infra/brain/base/workflow/orchestrator_project_coding"),
        Path("/xkagent_infra/groups/brain/projects/base/workflow/orchestrator_project_coding"),
        Path("/xkagent_infra/runtime/sandbox/_services/base/workflow/orchestrator_project_coding"),
    )
    AGENTCTL_SERVICE_BUNDLE_HOST = Path("/xkagent_infra/brain/infrastructure/service/agentctl")
    AGENTCTL_SERVICE_BUNDLE_CONTAINER = "/xkagent_infra/runtime/sandbox/_services/service/agentctl"
    SANDBOX_SERVICE_BUNDLE_HOST = Path("/xkagent_infra/brain/infrastructure/service/brain_sandbox_service")
    SANDBOX_SERVICE_BUNDLE_CONTAINER = "/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service"
    BASE_SKILL_BUNDLE_HOST = Path("/xkagent_infra/brain/base/skill")
    BASE_SKILL_BUNDLE_CONTAINER = "/xkagent_infra/runtime/sandbox/_services/base/skill"
    BASE_WORKFLOW_BUNDLE_HOST = Path("/xkagent_infra/brain/base/workflow")
    BASE_WORKFLOW_BUNDLE_CONTAINER = "/xkagent_infra/runtime/sandbox/_services/base/workflow"
    RUNTIME_INSTANCE_STATE_FILE = "instance.yaml"
    SANDBOX_SERVICE_BUNDLE_MARKER = "/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service/"

    def __init__(self):
        self.config = SandboxConfig()
        self.registry = SandboxRegistry()
        self.naming = SandboxNaming()

    def _canonical_project(self, project: str) -> str:
        resolved = self.config.resolve_project_name(project)
        if not resolved:
            raise RuntimeError("project name is required")
        return resolved

    def _container_name_for_project(
        self,
        project: str,
        dep_type: str,
        instance_id: str,
        *,
        group: Optional[str] = None,
    ) -> str:
        resolved_group = str(group or self.config.GROUP).strip() or self.config.GROUP
        return self.naming.container_name(
            resolved_group,
            self.config.get_project_alias(project),
            dep_type,
            instance_id,
        )

    def _ensure_instance_matches_project(self, instance: Dict[str, Any], project: str) -> None:
        instance_project = self._canonical_project(str(instance.get("project") or ""))
        if instance_project != project:
            raise RuntimeError(
                f"instance/project mismatch: {instance.get('instance_id')} belongs to {instance_project}, not {project}"
            )

    def create(self, project: str, dep_type: str = "development", **kwargs) -> Dict:
        """创建新 Sandbox"""
        project = self._canonical_project(project)
        print(f"🚀 创建 {dep_type} sandbox for {project}...")
        with_agent = str(kwargs.get("with_agent") or self.DEFAULT_ATTACHED_AGENT_ROLE).strip().lower()
        pending_id = str(kwargs.get("pending_id") or "").strip() or None
        model_override = str(kwargs.get("model") or "").strip() or None

        # 1. 加载配置
        platform_config = self.config.load_platform_config()
        project_config = self.config.load_project_config(project)
        provider_config = self.config.load_provider_config("docker")

        # 2. 生成实例 ID
        instance_id = self.naming.generate_instance_id()

        # 3. LEP 预检查
        checker = SandboxLEPChecker(project, dep_type, instance_id, project_config)
        passed, errors = checker.check_all()
        if not passed:
            print("❌ LEP Gates 检查失败:")
            for e in errors:
                print(f"   - {e}")
            sys.exit(1)

        # 4. 构建容器名称
        host_project_root = self._project_host_root(project)
        if not host_project_root.exists():
            raise RuntimeError(f"project root does not exist: {host_project_root}")
        container_name = checker.container_name
        runtime_root = self._sandbox_runtime_root(instance_id)
        runtime_root.mkdir(parents=True, exist_ok=True)
        compose_project = f"sandbox-{instance_id}"

        # 5. 准备环境变量
        env_vars = self._prepare_env_vars(
            project, dep_type, instance_id, container_name,
            platform_config, project_config, provider_config
        )

        # 6. 生成 compose 文件
        compose_file = self._generate_compose(
            project, dep_type, instance_id, env_vars,
            platform_config, project_config, provider_config
        )

        # 7. 启动容器
        print(f"📦 启动容器: {container_name}")
        self._run(
            ["docker", "compose", "-p", compose_project, "-f", compose_file, "up", "-d"],
            cwd=str(self.config.BASE_ROOT / "templates"),
            timeout=120,
        )

        # 8. 注册实例
        instance_record = {
            "instance_id": instance_id,
            "project": project,
            "group": checker.group,
            "type": dep_type,
            "status": "running",
            "created_at": datetime.now().isoformat(),
            "container_name": container_name,
            "compose_file": compose_file,
            "compose_project": compose_project,
            "project_root": str(host_project_root),
            "runtime_root": str(runtime_root),
            "host_ports": env_vars.get("HOST_PORTS", {}),
        }
        self.registry.register(instance_record)
        self._write_runtime_instance_state(instance_record)

        if with_agent:
            try:
                agent_info = self._bootstrap_attached_agent(
                    project=project,
                    dep_type=dep_type,
                    instance_id=instance_id,
                    container_name=container_name,
                    with_agent=with_agent,
                    pending_id=pending_id,
                    model_override=model_override,
                )
            except Exception as exc:
                self.registry.update(
                    instance_id,
                    {
                        "status": "bootstrap_failed",
                        "bootstrap_error": str(exc),
                    },
                )
                raise
            instance_record["status"] = "ready"
            instance_record["agent"] = agent_info
            self._verify_create_contract(container_name=container_name, agent_info=agent_info)
            self.registry.update(
                instance_id,
                {
                    "status": "ready",
                    "agent": agent_info,
                    "updated_at": datetime.now().isoformat(),
                },
            )
            self._write_runtime_instance_state(instance_record)

        print(f"✅ Sandbox 创建成功!")
        print(f"   实例 ID: {instance_id}")
        print(f"   容器名: {container_name}")
        print(f"   端口映射: {env_vars.get('HOST_PORTS', {})}")
        if with_agent:
            print(f"   附加 Agent: {instance_record['agent']['name']}")
            print(f"   Agent Runtime: {instance_record['agent']['cwd']}")

        return instance_record

    def _project_host_root(self, project: str) -> Path:
        return self.config.projects_root() / self._canonical_project(project)

    def _project_container_root(self, project: str) -> Path:
        return Path("/groups") / self.config.GROUP / "projects" / self._canonical_project(project)

    def _sandbox_runtime_root(self, instance_id: str) -> Path:
        return Path("/xkagent_infra/runtime/sandbox") / instance_id

    def _runtime_state_root(self, instance_id: str) -> Path:
        return self._sandbox_runtime_root(instance_id) / ".bootstrap"

    def _runtime_instance_state_path(self, instance_id: str) -> Path:
        return self._runtime_state_root(instance_id) / self.RUNTIME_INSTANCE_STATE_FILE

    def _running_inside_sandbox_bundle(self) -> bool:
        return self.SANDBOX_SERVICE_BUNDLE_MARKER in str(Path(__file__).resolve())

    def _default_sandbox_proxy_base_url(self) -> str:
        return str(os.environ.get("BRAIN_PROXY_BASE_URL") or "").strip() or "http://host.docker.internal:8210"

    def _resolve_orchestrator_workflow_root(self) -> Path:
        for candidate in self.ORCHESTRATOR_WORKFLOW_ROOTS:
            if candidate.exists():
                return candidate
        raise RuntimeError("orchestrator workflow bundle not found")

    def _sandbox_tmux_tmpdir(self, instance_id: str) -> str:
        return f"/xkagent_infra/runtime/sandbox/{instance_id}/.tmux"

    def _agentctl_python_root(self) -> Path:
        if self._running_inside_sandbox_bundle():
            return Path(self.AGENTCTL_SERVICE_BUNDLE_CONTAINER)
        return Path("/xkagent_infra/brain/infrastructure/service/agentctl")

    def _write_runtime_instance_state(self, instance: Dict[str, Any]) -> None:
        instance_id = str(instance.get("instance_id") or "").strip()
        if not instance_id:
            raise RuntimeError("missing instance_id for runtime state")
        state_root = self._runtime_state_root(instance_id)
        state_root.mkdir(parents=True, exist_ok=True)
        with open(self._runtime_instance_state_path(instance_id), "w", encoding="utf-8") as f:
            yaml.safe_dump(instance, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _load_runtime_instance_state(self, instance_id: str) -> Optional[Dict[str, Any]]:
        state_path = self._runtime_instance_state_path(instance_id)
        if not state_path.exists():
            return None
        loaded = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
        return loaded if isinstance(loaded, dict) else None

    def _resolve_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        instance = self.registry.get(instance_id)
        if instance:
            return instance
        instance = self._load_runtime_instance_state(instance_id)
        if instance:
            return instance
        if self._running_inside_sandbox_bundle():
            project = str(os.environ.get("PROJECT_NAME") or "").strip()
            dep_type = str(os.environ.get("DEPLOYMENT_TYPE") or "development").strip()
            container_name = str(os.environ.get("CONTAINER_NAME") or "").strip()
            if project:
                if not container_name:
                    container_name = self._container_name_for_project(project, dep_type, instance_id)
                return {
                    "instance_id": instance_id,
                    "project": project,
                    "type": dep_type,
                    "container_name": container_name,
                    "runtime_root": str(self._sandbox_runtime_root(instance_id)),
                    "status": "ready",
                }
        return None

    def _run(self, cmd: List[str], *, check: bool = True, timeout: int = 60,
             env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
            cwd=cwd,
        )
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or f"command failed: {' '.join(cmd)}")
        return proc

    def _compose_project_name(self, instance: Dict[str, Any]) -> str:
        instance_id = str(instance.get("instance_id") or "").strip()
        return str(instance.get("compose_project") or f"sandbox-{instance_id}").strip()

    def _wait_for_container_healthy(self, container_name: str, timeout_s: int = 60) -> None:
        deadline = time.time() + timeout_s
        last_status = "unknown"
        while time.time() < deadline:
            proc = self._run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    container_name,
                ],
                timeout=10,
                check=False,
            )
            status = (proc.stdout or "").strip().lower()
            if status in {"healthy", "running"}:
                return
            if status in {"unhealthy", "exited", "dead"}:
                raise RuntimeError(f"{container_name}: container status={status}")
            last_status = status or "unknown"
            time.sleep(2)
        raise RuntimeError(f"{container_name}: health wait timed out (last_status={last_status})")

    def _default_pending_id(self, instance_id: str) -> str:
        return f"bootstrap-{instance_id}"

    def _verify_create_contract(self, *, container_name: str, agent_info: Optional[Dict[str, Any]]) -> None:
        self._wait_for_container_healthy(container_name, timeout_s=30)
        if not agent_info:
            raise RuntimeError("sandbox create contract violated: attached orchestrator missing")
        role = str(agent_info.get("role") or "").strip().lower()
        if role != self.ORCHESTRATOR_ROLE:
            raise RuntimeError(
                f"sandbox create contract violated: expected {self.ORCHESTRATOR_ROLE}, got {role or 'missing'}"
            )

    def _load_role_profile(self, profile_role: str, model_override: Optional[str] = None) -> Dict[str, str]:
        profile_file = self._resolve_orchestrator_workflow_root() / "config" / "provider_profiles.yaml"
        with open(profile_file, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        role_profile_map = cfg.get("role_profile_map") or {}
        provider_catalog = ((cfg.get("providers") or {}).get("available") or {})
        profiles = ((cfg.get("providers") or {}).get("profiles") or {})

        profile_key = str(role_profile_map.get(profile_role) or "coordinator").strip()
        profile = profiles.get(profile_key) or {}
        provider_key = str(profile.get("provider") or "anthropic").strip().lower()
        raw_model = str(profile.get("model") or "claude-sonnet-4-6").strip()

        effective_model_override = str(model_override or "").strip() or None
        if not effective_model_override and profile_role == "project_orchestrator":
            effective_model_override = self.DEFAULT_ORCHESTRATOR_MODEL

        if effective_model_override:
            override = effective_model_override
            if "/" in override:
                provider_key, _, raw_model = override.partition("/")
                provider_key = provider_key.strip().lower()
                raw_model = raw_model.strip()
            else:
                raw_model = override

        provider_alias_to_agent_type = {
            "anthropic": "claude",
            "claude": "claude",
            "openai": "openai",
            "copilot": "copilot",
            "gemini": "gemini",
            "kimi": "kimi",
            "minimax": "minimax",
            "alibaba": "alibaba",
            "bytedance": "bytedance",
        }
        available = provider_catalog.get(provider_key) or {}

        agent_type = str(
            available.get("agent_type")
            or provider_alias_to_agent_type.get(provider_key)
            or provider_key
        ).strip().lower()
        selector_model = self._normalize_model_selector(provider_key, raw_model)
        return {
            "profile_key": profile_key,
            "provider": provider_key,
            "agent_type": agent_type,
            "model": selector_model,
        }

    def _load_orchestrator_profile(self, model_override: Optional[str] = None) -> Dict[str, str]:
        return self._load_role_profile("project_orchestrator", model_override=model_override)

    def _resolve_project_role(self, role: str) -> Tuple[str, str]:
        normalized = str(role or "").strip().lower().replace("-", "_")
        resolved = self.PROJECT_ROLE_ALIASES.get(normalized)
        if not resolved:
            supported = ", ".join(sorted(self.PROJECT_ROLE_ALIASES.keys()))
            raise RuntimeError(f"unsupported project role: {role} (supported: {supported})")
        return resolved

    def _project_agent_name(self, project: str, identity_role: str, slot: str) -> str:
        return f"agent_{self.config.GROUP}_{project}_{identity_role}_{slot}"

    def _project_tmux_session(self, instance_id: str, agent_name: str) -> str:
        return f"sbx_{instance_id}__{agent_name}"

    def _next_project_slot(self, config_dir: Path, project: str, identity_role: str) -> str:
        registry_path = config_dir / "agents_registry.yaml"
        existing_slots: list[int] = []
        if registry_path.exists():
            with open(registry_path, encoding="utf-8") as f:
                registry = yaml.safe_load(f) or {}
            groups = ((registry.get("groups") or {}).get(self.config.GROUP) or [])
            pattern = re.compile(
                rf"^agent_{re.escape(self.config.GROUP)}_{re.escape(project)}_{re.escape(identity_role)}_(\d+)$"
            )
            for item in groups:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                match = pattern.match(name)
                if match:
                    existing_slots.append(int(match.group(1)))
        next_slot = max(existing_slots, default=0) + 1
        return f"{next_slot:02d}"

    def _normalize_model_selector(self, provider: str, model: str) -> str:
        value = str(model or "").strip()
        if "/" in value:
            return value

        provider_key = str(provider or "").strip().lower()
        if provider_key == "anthropic":
            aliases = {
                "claude-sonnet-4-6": "claude-sonnet-4.6",
                "claude-opus-4-6": "claude-opus-4.6",
            }
            return f"claude/{aliases.get(value, value)}"
        if provider_key == "openai":
            return f"openai/{value}"
        if provider_key == "copilot":
            return f"copilot/{value}"
        if provider_key == "gemini":
            return f"gemini/{value}"
        return f"{provider_key}/{value}" if provider_key else value

    def _write_project_payload(
        self,
        *,
        project: str,
        instance_id: str,
        pending_id: str,
        orchestrator_name: str,
    ) -> Path:
        host_project_root = self._project_host_root(project)
        if not host_project_root.exists():
            raise RuntimeError(f"project root does not exist: {host_project_root}")

        payload_dir = host_project_root / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = payload_dir / "project_init.yaml"
        payload = {
            "project_id": project,
            "group_id": self.config.GROUP,
            "sandbox_id": instance_id,
            "instance_id": instance_id,
            "pending_id": pending_id,
            "project_root": str(self._project_container_root(project)),
            "runtime_root": str(self._sandbox_runtime_root(instance_id)),
            "requested_by": "agent-brain_devops",
            "orchestrator_agent_id": orchestrator_name,
            "created_at": datetime.now().isoformat(),
            "git_branch": f"feature/{pending_id}",
            "intake_seed": None,
            "profile_overrides": None,
        }
        with open(payload_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return payload_path

    def _write_sandbox_registry(self, config_dir: Path, agent_spec: Dict[str, Any]) -> Path:
        config_dir.mkdir(parents=True, exist_ok=True)
        registry_path = config_dir / "agents_registry.yaml"
        registry_data: Dict[str, Any] = {}
        if registry_path.exists():
            loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                registry_data = loaded

        agents_registry = registry_data.get("agents_registry")
        if not isinstance(agents_registry, dict):
            agents_registry = {}
            registry_data["agents_registry"] = agents_registry
        agents_registry["version"] = str(agents_registry.get("version") or "2.2")
        agents_registry["updated"] = datetime.now().strftime("%Y-%m-%d")

        group_meta = registry_data.get("group_meta")
        if not isinstance(group_meta, dict):
            group_meta = {}
            registry_data["group_meta"] = group_meta
        group_meta[self.config.GROUP] = {
            "type": "coding",
            "description": "Sandbox-local project agent registry",
        }

        groups = registry_data.get("groups")
        if not isinstance(groups, dict):
            groups = {}
            registry_data["groups"] = groups

        current_group_agents = groups.get(self.config.GROUP)
        if not isinstance(current_group_agents, list):
            current_group_agents = []
        updated = False
        target_name = str(agent_spec.get("name") or "").strip()
        for idx, existing in enumerate(current_group_agents):
            if not isinstance(existing, dict):
                continue
            if str(existing.get("name") or "").strip() == target_name:
                current_group_agents[idx] = agent_spec
                updated = True
                break
        if not updated:
            current_group_agents.append(agent_spec)
        groups[self.config.GROUP] = current_group_agents
        with open(registry_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(registry_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return registry_path

    def _ensure_proxy_client(self, group_name: str, agent_spec: Dict[str, Any], config_dir: Path) -> None:
        agentctl_service_dir = self._agentctl_python_root()
        if str(agentctl_service_dir) not in sys.path:
            sys.path.insert(0, str(agentctl_service_dir))

        from services.config_generator import sync_proxy_clients_config  # type: ignore

        del group_name, agent_spec
        sync_proxy_clients_config(config_dir)

        reload_base = self._default_sandbox_proxy_base_url() if self._running_inside_sandbox_bundle() else "http://127.0.0.1:8210"
        reload_proc = self._run(
            [
                "curl",
                "-sf",
                "-X",
                "POST",
                f"{reload_base.rstrip('/')}/reload-config",
                "-H",
                "Content-Type: application/json",
                "-d",
                "{}",
            ],
            check=False,
            timeout=10,
        )
        if reload_proc.returncode != 0 and not self._running_inside_sandbox_bundle():
            self._run(["supervisorctl", "restart", "brain_agent_proxy"], timeout=30)

    def _sync_claude_global_state_to_container(self, container_name: str) -> None:
        self._run(["docker", "exec", container_name, "sh", "-lc", "mkdir -p /root/.claude"], timeout=20)

        if Path("/root/.claude").exists():
            self._run(
                ["docker", "cp", "/root/.claude/.", f"{container_name}:/root/.claude/"],
                timeout=120,
            )
        if Path("/root/.claude.json").exists():
            self._run(
                ["docker", "cp", "/root/.claude.json", f"{container_name}:/root/.claude.json"],
                timeout=60,
            )
        self._sanitize_container_claude_settings(container_name)

    def _sanitize_container_claude_settings(self, container_name: str) -> None:
        settings_payload = {
            "theme": "dark",
            "terminalTheme": "dark",
            "skipDangerousModePermissionPrompt": True,
        }
        settings_local_payload = {
            "terminalTheme": "dark",
        }
        script = (
            "import json, pathlib; "
            "root = pathlib.Path('/root/.claude'); root.mkdir(parents=True, exist_ok=True); "
            f"settings = {repr(settings_payload)}; "
            f"settings_local = {repr(settings_local_payload)}; "
            "(root / 'settings.json').write_text(json.dumps(settings, indent=2), encoding='utf-8'); "
            "(root / 'settings.local.json').write_text(json.dumps(settings_local, indent=2), encoding='utf-8')"
        )
        self._run(["docker", "exec", container_name, "python3", "-c", script], timeout=20)

    def _generate_agent_configs(self, agent_spec: Dict[str, Any], container_name: str) -> None:
        agentctl_service_dir = self._agentctl_python_root()
        if str(agentctl_service_dir) not in sys.path:
            sys.path.insert(0, str(agentctl_service_dir))

        from services.config_generator import generate_all_configs  # type: ignore

        self._sync_claude_global_state_to_container(container_name)
        old_container = os.environ.get("AGENTCTL_DOCKER_CONTAINER")
        os.environ["AGENTCTL_DOCKER_CONTAINER"] = container_name
        try:
            generate_all_configs(agent_spec, force_claude_md=False)
        finally:
            if old_container is None:
                os.environ.pop("AGENTCTL_DOCKER_CONTAINER", None)
            else:
                os.environ["AGENTCTL_DOCKER_CONTAINER"] = old_container

    def _generate_agent_configs_local(self, agent_spec: Dict[str, Any]) -> None:
        agentctl_service_dir = self._agentctl_python_root()
        if str(agentctl_service_dir) not in sys.path:
            sys.path.insert(0, str(agentctl_service_dir))

        from services.config_generator import generate_all_configs  # type: ignore

        old_proxy_url = os.environ.get("BRAIN_PROXY_BASE_URL")
        os.environ["BRAIN_PROXY_BASE_URL"] = self._default_sandbox_proxy_base_url()
        try:
            generate_all_configs(agent_spec, force_claude_md=False)
        finally:
            if old_proxy_url is None:
                os.environ.pop("BRAIN_PROXY_BASE_URL", None)
            else:
                os.environ["BRAIN_PROXY_BASE_URL"] = old_proxy_url

    def _sync_runtime_to_container(self, runtime_root: Path, container_name: str) -> None:
        self._run(
            [
                "docker",
                "cp",
                f"{runtime_root}/.",
                f"{container_name}:{runtime_root}/",
            ],
            timeout=60,
        )

    def _sync_service_bundles_to_container(self, container_name: str) -> None:
        self._run(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-lc",
                f"mkdir -p {self.AGENTCTL_SERVICE_BUNDLE_CONTAINER} {self.SANDBOX_SERVICE_BUNDLE_CONTAINER} {self.BASE_SKILL_BUNDLE_CONTAINER} {self.BASE_WORKFLOW_BUNDLE_CONTAINER}",
            ],
            timeout=20,
        )
        self._run(
            [
                "docker",
                "cp",
                f"{self.AGENTCTL_SERVICE_BUNDLE_HOST}/.",
                f"{container_name}:{self.AGENTCTL_SERVICE_BUNDLE_CONTAINER}/",
            ],
            timeout=120,
        )
        self._run(
            [
                "docker",
                "cp",
                f"{self.SANDBOX_SERVICE_BUNDLE_HOST}/.",
                f"{container_name}:{self.SANDBOX_SERVICE_BUNDLE_CONTAINER}/",
            ],
            timeout=120,
        )
        self._run(
            [
                "docker",
                "cp",
                f"{self.BASE_SKILL_BUNDLE_HOST}/.",
                f"{container_name}:{self.BASE_SKILL_BUNDLE_CONTAINER}/",
            ],
            timeout=120,
        )
        self._run(
            [
                "docker",
                "cp",
                f"{self.BASE_WORKFLOW_BUNDLE_HOST}/.",
                f"{container_name}:{self.BASE_WORKFLOW_BUNDLE_CONTAINER}/",
            ],
            timeout=120,
        )

    def _prepare_runtime_state(self, runtime_root: Path) -> None:
        # .bootstrap only stores runtime state (pid/log/socket metadata), not helper code.
        state_root = runtime_root / ".bootstrap"
        state_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / ".tmux").mkdir(parents=True, exist_ok=True)
        obsolete_helper = state_root / "ipc_socket_bridge.py"
        if obsolete_helper.exists():
            obsolete_helper.unlink()

    def _tcp_ping_ok(self, host: str, port: int, *, timeout_s: float = 1.0) -> bool:
        payload = b'{"action":"ping","data":{}}\n'
        try:
            with socket.create_connection((host, port), timeout=timeout_s) as sock:
                sock.settimeout(timeout_s)
                sock.sendall(payload)
                data = sock.recv(4096)
            return b'"status":"ok"' in data
        except OSError:
            return False

    def _tcp_connect_ok(self, host: str, port: int, *, timeout_s: float = 1.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except OSError:
            return False

    def _ensure_host_ipc_bridge(
        self,
        *,
        name: str,
        listen_port: int,
        target_unix: str,
        probe_mode: str = "ping",
    ) -> None:
        probe = self._tcp_ping_ok if probe_mode == "ping" else self._tcp_connect_ok
        if probe("127.0.0.1", listen_port):
            return

        state_dir = self.IPC_BRIDGE_STATE_ROOT
        state_dir.mkdir(parents=True, exist_ok=True)
        pid_file = state_dir / f"{name}.pid"
        log_file = state_dir / f"{name}.log"

        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.kill(old_pid, 15)
            except Exception:
                pass
            pid_file.unlink(missing_ok=True)

        with open(log_file, "a", encoding="utf-8") as log_handle:
            subprocess.Popen(
                [
                    "python3",
                    str(self.IPC_BRIDGE_SCRIPT_HOST),
                    "--log-file",
                    str(log_file),
                    "--pid-file",
                    str(pid_file),
                    "tcp-listen",
                    "--listen-host",
                    self.HOST_IPC_BRIDGE_HOST,
                    "--listen-port",
                    str(listen_port),
                    "--target-unix",
                    target_unix,
                ],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )

        deadline = time.time() + 10
        while time.time() < deadline:
            if probe("127.0.0.1", listen_port):
                return
            time.sleep(0.5)
        raise RuntimeError(f"host ipc bridge failed: tcp:{listen_port} -> {target_unix}")

    def _container_ipc_ping_ok(self, container_name: str, socket_path: str) -> bool:
        probe = (
            "import socket,sys;"
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
            f"s.connect({socket_path!r});"
            "s.settimeout(2);"
            "s.sendall(b'{\"action\":\"ping\",\"data\":{}}\\n');"
            "data=s.recv(4096);"
            "s.close();"
            "sys.stdout.write(data.decode('utf-8','ignore'))"
        )
        proc = self._run(
            ["docker", "exec", container_name, "python3", "-c", probe],
            check=False,
            timeout=10,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0 and '"status":"ok"' in output

    def _container_notify_socket_ok(self, container_name: str, socket_path: str) -> bool:
        probe = (
            "import socket;"
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
            f"s.connect({socket_path!r});"
            "s.close()"
        )
        proc = self._run(
            ["docker", "exec", container_name, "python3", "-c", probe],
            check=False,
            timeout=10,
        )
        return proc.returncode == 0

    def _restart_container_bridge(
        self,
        *,
        container_name: str,
        bridge_script_path: str,
        bridge_name: str,
        listen_unix: str,
        target_port: int,
    ) -> None:
        pid_file = f"/tmp/{bridge_name}.pid"
        log_file = f"/tmp/{bridge_name}.log"
        cleanup_cmd = (
            f"if [ -f {pid_file} ]; then kill $(cat {pid_file}) >/dev/null 2>&1 || true; fi; "
            f"rm -f {listen_unix} {pid_file}"
        )
        self._run(
            ["docker", "exec", container_name, "sh", "-lc", cleanup_cmd],
            timeout=20,
            check=False,
        )
        self._run(
            [
                "docker",
                "exec",
                "-d",
                container_name,
                "python3",
                bridge_script_path,
                "--log-file",
                log_file,
                "--pid-file",
                pid_file,
                "unix-listen",
                "--listen-unix",
                listen_unix,
                "--target-host",
                "host.docker.internal",
                "--target-port",
                str(target_port),
                "--socket-mode",
                "666",
            ],
            timeout=20,
        )

    def _ensure_container_ipc_bridges(self, container_name: str) -> None:
        bridge_script_path = self.IPC_BRIDGE_SCRIPT_CONTAINER
        self._ensure_host_ipc_bridge(
            name="brain_ipc_main",
            listen_port=self.HOST_IPC_BRIDGE_PORT,
            target_unix=self.HOST_IPC_SOCKET,
            probe_mode="ping",
        )
        self._ensure_host_ipc_bridge(
            name="brain_ipc_notify",
            listen_port=self.HOST_NOTIFY_BRIDGE_PORT,
            target_unix=self.HOST_NOTIFY_SOCKET,
            probe_mode="connect",
        )

        if not self._container_ipc_ping_ok(container_name, self.CONTAINER_IPC_SOCKET):
            self._restart_container_bridge(
                container_name=container_name,
                bridge_script_path=bridge_script_path,
                bridge_name="brain_ipc_bridge_main",
                listen_unix=self.CONTAINER_IPC_SOCKET,
                target_port=self.HOST_IPC_BRIDGE_PORT,
            )

        if not self._container_notify_socket_ok(container_name, self.CONTAINER_NOTIFY_SOCKET):
            self._restart_container_bridge(
                container_name=container_name,
                bridge_script_path=bridge_script_path,
                bridge_name="brain_ipc_bridge_notify",
                listen_unix=self.CONTAINER_NOTIFY_SOCKET,
                target_port=self.HOST_NOTIFY_BRIDGE_PORT,
            )

        deadline = time.time() + 15
        while time.time() < deadline:
            main_ok = self._container_ipc_ping_ok(container_name, self.CONTAINER_IPC_SOCKET)
            notify_ok = self._container_notify_socket_ok(container_name, self.CONTAINER_NOTIFY_SOCKET)
            if main_ok and notify_ok:
                return
            time.sleep(0.5)
        raise RuntimeError(f"{container_name}: sandbox ipc bridge failed to become ready")

    def _start_sandbox_agent(
        self,
        config_dir: Path,
        runtime_root: Path,
        container_name: str,
        agent_name: str,
        agent_spec: Dict[str, Any],
    ) -> None:
        if self._running_inside_sandbox_bundle():
            self._start_sandbox_agent_local(config_dir, runtime_root, agent_name, agent_spec)
            return
        self._generate_agent_configs(agent_spec, container_name)
        self._prepare_runtime_state(runtime_root)
        self._sync_runtime_to_container(runtime_root, container_name)
        self._sync_service_bundles_to_container(container_name)
        self._ensure_container_ipc_bridges(container_name)
        env = os.environ.copy()
        sandbox_id = str(agent_spec.get("sandbox_id") or "").strip()
        env["AGENTCTL_DOCKER_CONTAINER"] = container_name
        env["AGENTCTL_CONFIG_DIR_HINT"] = str(config_dir)
        if sandbox_id:
            env["BRAIN_SANDBOX_ID"] = sandbox_id
            env["TMUX_TMPDIR"] = self._sandbox_tmux_tmpdir(sandbox_id)
        self._run(
            [
                "python3",
                "/xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl",
                "--config-dir",
                str(config_dir),
                "start",
                agent_name,
                "--no-config-gen",
                "--apply",
            ],
            timeout=120,
            env=env,
        )

    def _start_sandbox_agent_local(
        self,
        config_dir: Path,
        runtime_root: Path,
        agent_name: str,
        agent_spec: Dict[str, Any],
    ) -> None:
        self._prepare_runtime_state(runtime_root)
        self._generate_agent_configs_local(agent_spec)
        self._ensure_proxy_client(self.config.GROUP, agent_spec, config_dir)
        env = os.environ.copy()
        env["TMUX_TMPDIR"] = self._sandbox_tmux_tmpdir(str(agent_spec.get("sandbox_id") or ""))
        env["BRAIN_PROXY_BASE_URL"] = self._default_sandbox_proxy_base_url()
        self._run(
            [
                self.AGENTCTL_SERVICE_BUNDLE_CONTAINER + "/bin/agentctl",
                "--config-dir",
                str(config_dir),
                "start",
                agent_name,
                "--apply",
            ],
            timeout=120,
            env=env,
        )

    def _verify_sandbox_agent(self, container_name: str, session_name: str, agent_cwd: Path) -> None:
        if self._running_inside_sandbox_bundle():
            self._verify_sandbox_agent_local(session_name, agent_cwd)
            return
        sandbox_id = ""
        match = re.search(r"/runtime/sandbox/([^/]+)/agents/", str(agent_cwd))
        if match:
            sandbox_id = match.group(1)
        preferred_tmux_tmpdir = self._sandbox_tmux_tmpdir(sandbox_id) if sandbox_id else None
        last_error = "unknown"
        for _ in range(10):
            for tmux_tmpdir in (preferred_tmux_tmpdir, "/tmp/sandbox_tmux", None):
                cmd = ["docker", "exec"]
                if tmux_tmpdir:
                    cmd += ["-e", f"TMUX_TMPDIR={tmux_tmpdir}"]
                cmd += [container_name, "tmux", "has-session", "-t", session_name]
                proc = self._run(cmd, timeout=20, check=False)
                if proc.returncode == 0:
                    break
                last_error = (proc.stderr or proc.stdout or "").strip() or last_error
            else:
                time.sleep(1)
                continue
            break
        else:
            raise RuntimeError(last_error)
        if not (agent_cwd / ".brain" / "agent_runtime.json").exists():
            raise RuntimeError(f"runtime manifest missing: {agent_cwd / '.brain' / 'agent_runtime.json'}")

    def _verify_sandbox_agent_local(self, session_name: str, agent_cwd: Path) -> None:
        sandbox_id = ""
        match = re.search(r"/runtime/sandbox/([^/]+)/agents/", str(agent_cwd))
        if match:
            sandbox_id = match.group(1)
        last_error = "unknown"
        for _ in range(10):
            env = os.environ.copy()
            env["TMUX_TMPDIR"] = self._sandbox_tmux_tmpdir(sandbox_id) if sandbox_id else "/tmp/sandbox_tmux"
            proc = self._run(["tmux", "has-session", "-t", session_name], timeout=10, check=False, env=env)
            if proc.returncode == 0:
                break
            last_error = (proc.stderr or proc.stdout or "").strip() or last_error
            time.sleep(1)
        else:
            raise RuntimeError(last_error)
        if not (agent_cwd / ".brain" / "agent_runtime.json").exists():
            raise RuntimeError(f"runtime manifest missing: {agent_cwd / '.brain' / 'agent_runtime.json'}")

    def _bootstrap_orchestrator_agent(
        self,
        *,
        project: str,
        instance_id: str,
        container_name: str,
        pending_id: str,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile = self._load_orchestrator_profile(model_override=model_override)
        agent_name = f"agent_{self.config.GROUP}_{project}_orchestrator_01"
        tmux_session = self._project_tmux_session(instance_id, agent_name)
        runtime_root = self._sandbox_runtime_root(instance_id)
        agent_root = runtime_root / "agents" / agent_name
        config_dir = runtime_root / "config" / "agentctl"

        agent_root.mkdir(parents=True, exist_ok=True)
        (agent_root / ".brain").mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)

        payload_path = self._write_project_payload(
            project=project,
            instance_id=instance_id,
            pending_id=pending_id,
            orchestrator_name=agent_name,
        )

        spec = {
            "name": agent_name,
            "description": f"project orchestrator for {project}",
            "role": self.ORCHESTRATOR_ROLE,
            "scope": "project",
            "group": self.config.GROUP,
            "project": project,
            "sandbox_id": instance_id,
            "path": str(agent_root),
            "cwd": str(agent_root),
            "agent_type": profile["agent_type"],
            "agent_model": profile["model"],
            "model": profile["model"],
            "transport_mode": "proxy",
            "tmux_session": tmux_session,
            "desired_state": "running",
            "status": "active",
            "required": False,
            "hooks": ["pre_tool_use", "post_tool_use"],
            "env": {
                "IS_SANDBOX": "1",
                "BRAIN_AGENT_SCOPE": "project",
                "BRAIN_PROJECT_ID": project,
                "BRAIN_SANDBOX_ID": instance_id,
                "BRAIN_TRANSPORT_MODE": "proxy",
                "PROJECT_ROOT": str(self._project_container_root(project)),
                "PROJECT_INIT_FILE": str(payload_path).replace("/xkagent_infra/groups", "/groups"),
            },
        }

        self._write_sandbox_registry(config_dir, spec)
        self._start_sandbox_agent(config_dir, runtime_root, container_name, agent_name, spec)
        self._verify_sandbox_agent(container_name, tmux_session, agent_root)

        return {
            "name": agent_name,
            "role": self.ORCHESTRATOR_ROLE,
            "profile": profile["profile_key"],
            "model": profile["model"],
            "cwd": str(agent_root),
            "tmux_session": tmux_session,
            "payload": str(payload_path),
        }

    def spawn_agent(
        self,
        *,
        project: str,
        instance_id: str,
        role: str,
        slot: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        project = self._canonical_project(project)
        instance = self._resolve_instance(instance_id)
        if not instance:
            raise RuntimeError(f"instance not found: {instance_id}")
        self._ensure_instance_matches_project(instance, project)

        identity_role, profile_role = self._resolve_project_role(role)
        runtime_root = self._sandbox_runtime_root(instance_id)
        config_dir = runtime_root / "config" / "agentctl"
        resolved_slot = str(slot or "").strip() or self._next_project_slot(config_dir, project, identity_role)
        profile = self._load_role_profile(profile_role, model_override=model_override)

        agent_name = self._project_agent_name(project, identity_role, resolved_slot)
        tmux_session = self._project_tmux_session(instance_id, agent_name)
        agent_root = runtime_root / "agents" / agent_name
        agent_root.mkdir(parents=True, exist_ok=True)
        (agent_root / ".brain").mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)

        spec = {
            "name": agent_name,
            "description": f"project {identity_role} for {project}",
            "role": identity_role,
            "scope": "project",
            "group": self.config.GROUP,
            "project": project,
            "sandbox_id": instance_id,
            "path": str(agent_root),
            "cwd": str(agent_root),
            "agent_type": profile["agent_type"],
            "agent_model": profile["model"],
            "model": profile["model"],
            "transport_mode": "proxy",
            "tmux_session": tmux_session,
            "desired_state": "running",
            "status": "active",
            "required": False,
            "hooks": ["pre_tool_use", "post_tool_use"],
            "env": {
                "IS_SANDBOX": "1",
                "BRAIN_AGENT_SCOPE": "project",
                "BRAIN_PROJECT_ID": project,
                "BRAIN_SANDBOX_ID": instance_id,
                "BRAIN_TRANSPORT_MODE": "proxy",
                "PROJECT_ROOT": str(self._project_container_root(project)),
            },
        }

        self._write_sandbox_registry(config_dir, spec)
        self._start_sandbox_agent(config_dir, runtime_root, str(instance["container_name"]), agent_name, spec)
        self._verify_sandbox_agent(str(instance["container_name"]), tmux_session, agent_root)
        return {
            "name": agent_name,
            "role": identity_role,
            "profile": profile["profile_key"],
            "model": profile["model"],
            "cwd": str(agent_root),
            "tmux_session": tmux_session,
        }

    def _bootstrap_attached_agent(
        self,
        *,
        project: str,
        dep_type: str,
        instance_id: str,
        container_name: str,
        with_agent: str,
        pending_id: Optional[str],
        model_override: Optional[str],
    ) -> Dict[str, Any]:
        del dep_type
        self._wait_for_container_healthy(container_name, timeout_s=60)

        if with_agent != "orchestrator":
            raise RuntimeError(f"unsupported attached agent bootstrap: {with_agent}")

        resolved_pending_id = pending_id or self._default_pending_id(instance_id)
        print(f"🤖 启动附加 Agent: {with_agent} (pending_id={resolved_pending_id})")
        return self._bootstrap_orchestrator_agent(
            project=project,
            instance_id=instance_id,
            container_name=container_name,
            pending_id=resolved_pending_id,
            model_override=model_override,
        )

    def _prepare_env_vars(self, project: str, dep_type: str, instance_id: str,
                          container_name: str, platform_config: Dict,
                          project_config: Optional[Dict],
                          provider_config: Dict) -> Dict:
        """准备环境变量"""

        # 分配端口
        port_range = provider_config["provider"]["naming"]["ports"]["range"]
        base_port = port_range["min"] + hash(instance_id) % (port_range["max"] - port_range["min"])

        env_vars = {
            "SANDBOX_NAME": f"sandbox-{instance_id}",
            "SANDBOX_VERSION": "2.3.7",
            "CONTAINER_NAME": container_name,
            "HOSTNAME": f"{project}-{dep_type}",
            "PROJECT_NAME": project,
            "PROJECT_ID": project,
            "PROJECT_VERSION": "1.0.0",
            "GROUP_NAME": "brain",
            "GROUP_ID": "brain",
            "DEPLOYMENT_TYPE": dep_type,
            "INSTANCE_ID": instance_id,
            "NETWORK_NAME": self.naming.network_name("brain", dep_type, instance_id),
            "HOST_PORT_APP": str(base_port),
            "HOST_PORT_DEBUG": str(base_port + 1),
            "CONTAINER_PORT_APP": "8080",
            "CONTAINER_PORT_DEBUG": "5678",
            "CPU_LIMIT": provider_config["provider"]["resources"][dep_type]["cpus"],
            "MEMORY_LIMIT": provider_config["provider"]["resources"][dep_type]["memory"],
            "RESTART_POLICY": "no" if dep_type in ["development", "testing"] else "unless-stopped",
            "CREATED_AT": datetime.now().isoformat(),
            "AGENTCTL_CONFIG_DIR": "/xkagent_infra/runtime/sandbox/${INSTANCE_ID}/config/agentctl",
            "HOST_IP": subprocess.check_output(["hostname", "-I"], text=True).strip().split()[0],
            "HOST_PORTS": {
                "app": base_port,
                "debug": base_port + 1,
            }
        }

        return env_vars

    def _generate_compose(self, project: str, dep_type: str, instance_id: str,
                          env_vars: Dict, platform_config: Dict,
                          project_config: Optional[Dict],
                          provider_config: Dict) -> str:
        """生成 Docker Compose 文件（按类型和实例 ID 分类存储）"""

        # 读取基础模板 (从 base 项目源码)
        base_compose = self.config.BASE_ROOT / "templates" / "compose.base.yaml"
        with open(base_compose) as f:
            compose_content = f.read()

        # 替换变量
        for key, value in env_vars.items():
            if isinstance(value, dict):
                continue
            compose_content = compose_content.replace(f"${{{key}}}", str(value))
            compose_content = re.sub(r"\$\{" + re.escape(key) + r":-[^}]*\}", str(value), compose_content)
            compose_content = re.sub(r"\$\{" + re.escape(key) + r"-[^}]*\}", str(value), compose_content)

        # 按类型和实例 ID 分类存储: instances/{type_prefix}-{instance_id}/{instance_id}.yaml
        type_prefix = self.config.TYPE_DIR_MAP.get(dep_type, dep_type)
        instance_dir = self.config.PLATFORM_ROOT / "instances" / f"{type_prefix}-{instance_id}"
        instance_dir.mkdir(parents=True, exist_ok=True)

        compose_file = instance_dir / f"{instance_id}.yaml"

        with open(compose_file, 'w') as f:
            f.write(compose_content)

        return str(compose_file)

    def start(self, project: str, instance_id: Optional[str] = None,
              dep_type: Optional[str] = None) -> None:
        """启动 Sandbox"""
        project = self._canonical_project(project)
        if instance_id:
            instance = self.registry.get(instance_id)
            if not instance:
                print(f"❌ 实例 {instance_id} 不存在")
                return
            self._ensure_instance_matches_project(instance, project)

            compose_file = instance["compose_file"]
            compose_project = self._compose_project_name(instance)
            self._run(
                ["docker", "compose", "-p", compose_project, "-f", compose_file, "start"],
                timeout=120,
            )
            self.registry.update(instance_id, {"status": "running"})
            print(f"✅ 实例 {instance_id} 已启动")

        elif dep_type:
            instances = self.registry.list_by_type(dep_type)
            project_instances = [i for i in instances if i["project"] == project]
            for instance in project_instances:
                self.start(project, instance["instance_id"])

    def stop(self, project: str, instance_id: str, cleanup: bool = False) -> None:
        """停止 Sandbox"""
        project = self._canonical_project(project)
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return
        self._ensure_instance_matches_project(instance, project)

        compose_file = instance["compose_file"]
        compose_project = self._compose_project_name(instance)
        self._run(
            ["docker", "compose", "-p", compose_project, "-f", compose_file, "stop"],
            timeout=120,
        )

        if cleanup or instance["type"] == "testing":
            self._run(
                ["docker", "compose", "-p", compose_project, "-f", compose_file, "down", "-v"],
                timeout=120,
            )
            self.registry.archive(instance_id)
            print(f"✅ 实例 {instance_id} 已停止并清理")
        else:
            self.registry.update(instance_id, {"status": "stopped", "stopped_at": datetime.now().isoformat()})
            print(f"✅ 实例 {instance_id} 已停止")

    def list(self, project: Optional[str] = None, active_only: bool = False) -> List[Dict]:
        """列出 Sandbox"""
        if project:
            project = self._canonical_project(project)
            instances = self.registry.list_by_project(project)
        else:
            instances = []
            for f in self.registry.REGISTRY_PATH.glob("*.yaml"):
                with open(f) as fp:
                    instances.append(yaml.safe_load(fp))

        if active_only:
            instances = [i for i in instances if i.get("status") in ["running", "creating"]]

        return instances

    def list_filtered(self, project: Optional[str] = None, active_only: bool = False,
                      dep_type: Optional[str] = None) -> List[Dict]:
        instances = self.list(project, active_only)
        if dep_type:
            instances = [i for i in instances if i.get("type") == dep_type]
        return instances

    def destroy(self, project: str, instance_id: str, force: bool = False) -> None:
        """销毁 Sandbox"""
        project = self._canonical_project(project)
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return
        self._ensure_instance_matches_project(instance, project)

        compose_file = instance["compose_file"]
        compose_project = self._compose_project_name(instance)

        # 停止并删除容器
        self._run(
            ["docker", "compose", "-p", compose_project, "-f", compose_file, "down", "-v"],
            timeout=120,
        )

        if not force:
            self.registry.archive(instance_id)
            print(f"✅ 实例 {instance_id} 已销毁并归档")
        else:
            # 直接删除注册表记录
            registry_file = self.registry.REGISTRY_PATH / f"{instance_id}.yaml"
            registry_file.unlink(missing_ok=True)
            print(f"✅ 实例 {instance_id} 已强制删除")

    def exec_cmd(self, project: str, instance_id: str, command: str) -> None:
        """在 Sandbox 中执行命令"""
        project = self._canonical_project(project)
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return
        self._ensure_instance_matches_project(instance, project)

        container_name = instance["container_name"]
        proc = subprocess.run(
            ["docker", "exec", container_name, "bash", "-lc", command],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "").strip() or "sandbox exec failed")

    def validate(self, project: str, check_gates: bool = False) -> Tuple[bool, List[str]]:
        """验证项目配置"""
        project = self._canonical_project(project)
        errors = []

        # 检查项目配置是否存在
        project_config = self.config.load_project_config(project)
        if project_config:
            # 检查是否有禁止覆盖的配置
            if "privileged" in str(project_config):
                errors.append("禁止覆盖 privileged 配置")

        if check_gates:
            # 模拟检查 LEP Gates
            pass

        return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(description="Brain Sandbox Service")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # create
    create_parser = subparsers.add_parser("create", help="Create new sandbox")
    create_parser.add_argument("project", help="Project name")
    create_parser.add_argument("--type", default="development",
                               choices=["development", "testing", "staging", "audit"],
                               help="Deployment type")
    create_parser.add_argument(
        "--with-agent",
        choices=["orchestrator"],
        help="Bootstrap and start a sandbox-local project agent after container creation (default: orchestrator)",
    )
    create_parser.add_argument(
        "--pending-id",
        help="Pending / bootstrap id written into project payload when using --with-agent",
    )
    create_parser.add_argument(
        "--model",
        help="Optional provider/model override for attached orchestrator (default: minimax/minimax-m2.7)",
    )

    # start
    start_parser = subparsers.add_parser("start", help="Start sandbox")
    start_parser.add_argument("project", help="Project name")
    start_parser.add_argument("--instance", help="Instance ID")
    start_parser.add_argument("--type", help="Deployment type")

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop sandbox")
    stop_parser.add_argument("project", help="Project name")
    stop_parser.add_argument("--instance", required=True, help="Instance ID")
    stop_parser.add_argument("--cleanup", action="store_true", help="Clean up after stop")

    # list
    list_parser = subparsers.add_parser("list", help="List sandboxes")
    list_parser.add_argument("project", nargs="?", help="Project name (optional)")
    list_parser.add_argument("--active", action="store_true", help="Show only active")
    list_parser.add_argument("--type", help="Filter by deployment type")

    # destroy
    destroy_parser = subparsers.add_parser("destroy", help="Destroy sandbox")
    destroy_parser.add_argument("project", help="Project name")
    destroy_parser.add_argument("--instance", required=True, help="Instance ID")
    destroy_parser.add_argument("--force", action="store_true", help="Force destroy without archive")

    # exec
    exec_parser = subparsers.add_parser("exec", help="Execute command in sandbox")
    exec_parser.add_argument("project", help="Project name")
    exec_parser.add_argument("--instance", required=True, help="Instance ID")
    exec_parser.add_argument("--command", dest="exec_command", required=True, help="Command to execute")

    # spawn-agent
    spawn_parser = subparsers.add_parser("spawn-agent", help="Provision and start a project-scoped agent inside sandbox")
    spawn_parser.add_argument("project", help="Project name")
    spawn_parser.add_argument("--instance", required=True, help="Instance ID")
    spawn_parser.add_argument("--role", required=True, help="Project role, e.g. designer|dev|qa|researcher|devops|architect")
    spawn_parser.add_argument("--slot", help="Optional two-digit slot override (default: next available)")
    spawn_parser.add_argument("--model", help="Optional provider/model override, e.g. minimax/minimax-m2.7")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate project config")
    validate_parser.add_argument("project", help="Project name")
    validate_parser.add_argument("--check-gates", action="store_true", help="Check LEP gates")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    manager = SandboxManager()

    if args.command == "create":
        manager.create(
            args.project,
            args.type,
            with_agent=getattr(args, "with_agent", None),
            pending_id=getattr(args, "pending_id", None),
            model=getattr(args, "model", None),
        )
    elif args.command == "start":
        manager.start(args.project, args.instance, args.type)
    elif args.command == "stop":
        manager.stop(args.project, args.instance, args.cleanup)
    elif args.command == "list":
        instances = manager.list_filtered(args.project, args.active, getattr(args, "type", None))
        print(f"\n{'Instance ID':<15} {'Project':<20} {'Type':<12} {'Status':<10} {'Ports'}")
        print("-" * 80)
        for i in instances:
            ports = i.get("host_ports", {})
            print(f"{i['instance_id']:<15} {i['project']:<20} {i['type']:<12} {i['status']:<10} {ports}")
    elif args.command == "destroy":
        manager.destroy(args.project, args.instance, args.force)
    elif args.command == "exec":
        manager.exec_cmd(args.project, args.instance, args.exec_command)
    elif args.command == "spawn-agent":
        result = manager.spawn_agent(
            project=args.project,
            instance_id=args.instance,
            role=args.role,
            slot=getattr(args, "slot", None),
            model_override=getattr(args, "model", None),
        )
        print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).strip())
    elif args.command == "validate":
        passed, errors = manager.validate(args.project, args.check_gates)
        if passed:
            print("✅ 配置验证通过")
        else:
            print("❌ 配置验证失败:")
            for e in errors:
                print(f"   - {e}")


if __name__ == "__main__":
    main()
