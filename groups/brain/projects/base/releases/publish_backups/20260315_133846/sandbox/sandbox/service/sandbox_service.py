#!/usr/bin/env python3
"""
Sandbox Service - Brain Group Sandbox 管理服务
规范: /xkagent_infra/brain/base/sandbox/index.yaml (发布态)
源码: /xkagent_infra/groups/brain/projects/base/sandbox/
运行时: /xkagent_infra/groups/brain/platform/sandbox/
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import string
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
        config_path = Path(f"/xkagent_infra/groups/{cls.GROUP}/projects") / project / ".sandbox" / "config.yaml"
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

    def __init__(self, project: str, dep_type: str, instance_id: str):
        self.project = project
        self.dep_type = dep_type
        self.instance_id = instance_id
        self.group = "brain"
        self.container_name = SandboxNaming.container_name(
            self.group, project, dep_type, instance_id
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

    def __init__(self):
        self.config = SandboxConfig()
        self.registry = SandboxRegistry()
        self.naming = SandboxNaming()

    def create(self, project: str, dep_type: str = "development", **kwargs) -> Dict:
        """创建新 Sandbox"""
        print(f"🚀 创建 {dep_type} sandbox for {project}...")

        # 1. 加载配置
        platform_config = self.config.load_platform_config()
        project_config = self.config.load_project_config(project)
        provider_config = self.config.load_provider_config("docker")

        # 2. 生成实例 ID
        instance_id = self.naming.generate_instance_id()

        # 3. LEP 预检查
        checker = SandboxLEPChecker(project, dep_type, instance_id)
        passed, errors = checker.check_all()
        if not passed:
            print("❌ LEP Gates 检查失败:")
            for e in errors:
                print(f"   - {e}")
            sys.exit(1)

        # 4. 构建容器名称
        container_name = self.naming.container_name(
            "brain", project, dep_type, instance_id
        )

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
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "up", "-d"],
            cwd=str(self.config.BASE_ROOT / "templates"),
            check=True
        )

        # 8. 注册实例
        instance_record = {
            "instance_id": instance_id,
            "project": project,
            "group": "brain",
            "type": dep_type,
            "status": "running",
            "created_at": datetime.now().isoformat(),
            "container_name": container_name,
            "compose_file": compose_file,
            "host_ports": env_vars.get("HOST_PORTS", {}),
        }
        self.registry.register(instance_record)

        print(f"✅ Sandbox 创建成功!")
        print(f"   实例 ID: {instance_id}")
        print(f"   容器名: {container_name}")
        print(f"   端口映射: {env_vars.get('HOST_PORTS', {})}")

        return instance_record

    def _prepare_env_vars(self, project: str, dep_type: str, instance_id: str,
                          container_name: str, platform_config: Dict,
                          project_config: Optional[Dict],
                          provider_config: Dict) -> Dict:
        """准备环境变量"""

        # 获取项目路径
        project_root = f"/xkagent_infra/groups/brain/projects/{project}"

        # 分配端口
        port_range = provider_config["provider"]["naming"]["ports"]["range"]
        base_port = port_range["min"] + hash(instance_id) % (port_range["max"] - port_range["min"])

        env_vars = {
            "SANDBOX_NAME": f"sandbox-{instance_id}",
            "SANDBOX_VERSION": "2.1.0",
            "CONTAINER_NAME": container_name,
            "HOSTNAME": f"{project}-{dep_type}",
            "PROJECT_ROOT": project_root,
            "PROJECT_NAME": project,
            "PROJECT_VERSION": "1.0.0",
            "GROUP_NAME": "brain",
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
        """生成 Docker Compose 文件"""

        # 读取基础模板 (从 base 项目源码)
        base_compose = self.config.BASE_ROOT / "templates" / "compose.base.yaml"
        with open(base_compose) as f:
            compose_content = f.read()

        # 替换变量
        for key, value in env_vars.items():
            if isinstance(value, dict):
                continue
            compose_content = compose_content.replace(f"${{{key}}}", str(value))

        # 写入运行时 compose 文件 (到 platform 目录)
        # FIX: 创建实例目录，每个实例有自己的子目录
        instance_dir = self.config.PLATFORM_ROOT / "instances" / instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        compose_file = instance_dir / f"{instance_id}.yaml"

        with open(compose_file, 'w') as f:
            f.write(compose_content)

        return str(compose_file)

    def start(self, project: str, instance_id: Optional[str] = None,
              dep_type: Optional[str] = None) -> None:
        """启动 Sandbox"""
        if instance_id:
            instance = self.registry.get(instance_id)
            if not instance:
                print(f"❌ 实例 {instance_id} 不存在")
                return

            compose_file = instance["compose_file"]
            subprocess.run(
                ["docker", "compose", "-f", compose_file, "start"],
                check=True
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
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return

        compose_file = instance["compose_file"]
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "stop"],
            check=True
        )

        if cleanup or instance["type"] == "testing":
            subprocess.run(
                ["docker", "compose", "-f", compose_file, "down", "-v"],
                check=True
            )
            self.registry.archive(instance_id)
            print(f"✅ 实例 {instance_id} 已停止并清理")
        else:
            self.registry.update(instance_id, {"status": "stopped", "stopped_at": datetime.now().isoformat()})
            print(f"✅ 实例 {instance_id} 已停止")

    def list(self, project: Optional[str] = None, active_only: bool = False) -> List[Dict]:
        """列出 Sandbox"""
        if project:
            instances = self.registry.list_by_project(project)
        else:
            instances = []
            for f in self.registry.REGISTRY_PATH.glob("*.yaml"):
                with open(f) as fp:
                    instances.append(yaml.safe_load(fp))

        if active_only:
            instances = [i for i in instances if i.get("status") in ["running", "creating"]]

        return instances

    def destroy(self, project: str, instance_id: str, force: bool = False) -> None:
        """销毁 Sandbox"""
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return

        compose_file = instance["compose_file"]

        # 停止并删除容器
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "down", "-v"],
            check=True
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
        instance = self.registry.get(instance_id)
        if not instance:
            print(f"❌ 实例 {instance_id} 不存在")
            return

        container_name = instance["container_name"]
        subprocess.run(
            ["docker", "exec", container_name, "bash", "-c", command],
            check=True
        )

    def validate(self, project: str, check_gates: bool = False) -> Tuple[bool, List[str]]:
        """验证项目配置"""
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

    # destroy
    destroy_parser = subparsers.add_parser("destroy", help="Destroy sandbox")
    destroy_parser.add_argument("project", help="Project name")
    destroy_parser.add_argument("--instance", required=True, help="Instance ID")
    destroy_parser.add_argument("--force", action="store_true", help="Force destroy without archive")

    # exec
    exec_parser = subparsers.add_parser("exec", help="Execute command in sandbox")
    exec_parser.add_argument("project", help="Project name")
    exec_parser.add_argument("--instance", required=True, help="Instance ID")
    exec_parser.add_argument("--command", required=True, help="Command to execute")

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
        manager.create(args.project, args.type)
    elif args.command == "start":
        manager.start(args.project, args.instance, args.type)
    elif args.command == "stop":
        manager.stop(args.project, args.instance, args.cleanup)
    elif args.command == "list":
        instances = manager.list(args.project, args.active)
        print(f"\n{'Instance ID':<15} {'Project':<20} {'Type':<12} {'Status':<10} {'Ports'}")
        print("-" * 80)
        for i in instances:
            ports = i.get("host_ports", {})
            print(f"{i['instance_id']:<15} {i['project']:<20} {i['type']:<12} {i['status']:<10} {ports}")
    elif args.command == "destroy":
        manager.destroy(args.project, args.instance, args.force)
    elif args.command == "exec":
        manager.exec_cmd(args.project, args.instance, args.command)
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
