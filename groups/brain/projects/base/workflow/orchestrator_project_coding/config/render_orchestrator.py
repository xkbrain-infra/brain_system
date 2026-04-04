#!/usr/bin/env python3
"""
渲染 orchestrator runtime 配置脚本

用法:
  python3 render_orchestrator.py --project-id XXX --group-id XXX \
    --project-root /path/to/project --output-dir /path/to/output \
    --workflow-root /path/to/workflow

功能:
  1. 解析 provider_profiles.yaml 获取 coordinator profile
  2. 渲染 AGENTS.md、.mcp.json、settings.local.json、agent_runtime.json
  3. 创建 orchestrator runtime 目录并写入配置文件
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml


def load_provider_profiles(workflow_root: str) -> dict:
    """加载 provider_profiles.yaml，解析 orchestrator 的 profile"""
    profile_file = Path(workflow_root) / "config" / "provider_profiles.yaml"
    with open(profile_file) as f:
        cfg = yaml.safe_load(f)

    role_profile_map = cfg.get("role_profile_map", {})
    profiles = cfg.get("providers", {}).get("profiles", {})

    role = "project_orchestrator"
    profile_key = role_profile_map.get(role, "coordinator")
    profile = profiles.get(profile_key, {})

    resolved_provider = profile.get("provider", "anthropic")
    resolved_model = profile.get("model", "claude-sonnet-4-6")
    fallback = profile.get("fallback", {})

    return {
        "profile_key": profile_key,
        "provider": resolved_provider,
        "model": resolved_model,
        "fallback_provider": fallback.get("provider"),
        "fallback_model": fallback.get("model"),
    }


def render_template(template_path: str, vars: dict) -> str:
    """用 envsubst 风格渲染模板"""
    with open(template_path) as f:
        content = f.read()

    # 简单的 ${VAR} 替换
    for key, value in vars.items():
        content = content.replace(f"${{{key}}}", str(value))
        content = content.replace(f"${{global_config.{key}}}", str(value))

    return content


def create_orchestrator_runtime(
    project_id: str,
    group_id: str,
    sandbox_id: str,
    pending_id: str,
    project_root: str,
    workflow_root: str,
    output_dir: str,
    brain_ipc_host: str,
    brain_ipc_port: str,
    brain_agentctl_host: str,
    brain_agentctl_port: str,
    brain_task_manager_host: str,
    brain_task_manager_port: str,
):
    """创建 orchestrator runtime 目录和配置文件"""

    # 解析 profile
    profile_info = load_provider_profiles(workflow_root)
    orch_id = f"agent_{group_id}_{project_id}_orchestrator_01"
    orch_dir = Path(output_dir) / orch_id
    orch_dir.mkdir(parents=True, exist_ok=True)
    (orch_dir / ".claude").mkdir(exist_ok=True)

    # 准备渲染变量
    render_vars = {
        "project_id": project_id,
        "group_id": group_id,
        "sandbox_id": sandbox_id,
        "pending_id": pending_id,
        "orchestrator_agent_id": orch_id,
        "runtime_home": str(orch_dir),
        "resolved_model": profile_info["model"],
        "profile_key": profile_info["profile_key"],
        "BRAIN_IPC_HOST": brain_ipc_host,
        "BRAIN_IPC_PORT": brain_ipc_port,
        "BRAIN_AGENTCTL_HOST": brain_agentctl_host,
        "BRAIN_AGENTCTL_PORT": brain_agentctl_port,
        "BRAIN_TASK_MANAGER_HOST": brain_task_manager_host,
        "BRAIN_TASK_MANAGER_PORT": brain_task_manager_port,
    }

    # 1. 渲染 AGENTS.md
    agents_template = Path(workflow_root) / "orchestrator_agents_md_template.md"
    agents_content = render_template(str(agents_template), render_vars)
    (orch_dir / "AGENTS.md").write_text(agents_content)
    print(f"Created: {orch_dir / 'AGENTS.md'}")

    # 2. 生成 .mcp.json
    mcp_config = {
        "mcpServers": {
            "brain_ipc": {
                "host": brain_ipc_host,
                "port": brain_ipc_port,
            },
            "task_manager": {
                "host": brain_task_manager_host,
                "port": brain_task_manager_port,
            },
            "agentctl": {
                "host": brain_agentctl_host,
                "port": brain_agentctl_port,
            },
        }
    }
    (orch_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2))
    print(f"Created: {orch_dir / '.mcp.json'}")

    # 3. claude settings
    settings = {
        "model": profile_info["model"],
        "permissions": {"allow": ["Read", "Write", "Bash", "MCP"]},
    }
    (orch_dir / ".claude" / "settings.local.json").write_text(
        json.dumps(settings, indent=2)
    )
    print(f"Created: {orch_dir / '.claude' / 'settings.local.json'}")

    # 4. agent_runtime.json
    runtime = {
        "agent_id": orch_id,
        "role": "project_orchestrator",
        "provider": profile_info["provider"],
        "model": profile_info["model"],
        "profile": profile_info["profile_key"],
        "working_dir": str(orch_dir),
        "startup_file": "AGENTS.md",
        "project_id": project_id,
        "group_id": group_id,
        "sandbox_id": sandbox_id,
    }
    (orch_dir / "agent_runtime.json").write_text(json.dumps(runtime, indent=2))
    print(f"Created: {orch_dir / 'agent_runtime.json'}")

    # 5. 写入 .env 文件供后续步骤使用
    env_file = orch_dir / ".env"
    env_content = f"""\
ORCHESTRATOR_ID={orch_id}
ORCHESTRATOR_DIR={orch_dir}
ORCHESTRATOR_MODEL={profile_info['model']}
ORCHESTRATOR_PROVIDER={profile_info['provider']}
ORCHESTRATOR_PROFILE={profile_info['profile_key']}
"""
    env_file.write_text(env_content)
    print(f"Created: {env_file}")

    print(f"\n✅ Orchestrator runtime created at: {orch_dir}")
    print(f"   Agent ID: {orch_id}")
    print(f"   Model: {profile_info['provider']}/{profile_info['model']}")
    print(f"   Profile: {profile_info['profile_key']}")

    return {
        "orch_id": orch_id,
        "orch_dir": str(orch_dir),
        "model": profile_info["model"],
        "provider": profile_info["provider"],
        "profile": profile_info["profile_key"],
    }


def main():
    parser = argparse.ArgumentParser(description="Render orchestrator runtime config")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--sandbox-id", required=True)
    parser.add_argument("--pending-id", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workflow-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--brain-ipc-host", default="brain-ipc")
    parser.add_argument("--brain-ipc-port", default="9800")
    parser.add_argument("--brain-agentctl-host", default="brain-agentctl")
    parser.add_argument("--brain-agentctl-port", default="9810")
    parser.add_argument("--brain-task-manager-host", default="brain-task-manager")
    parser.add_argument("--brain-task-manager-port", default="9820")

    args = parser.parse_args()

    create_orchestrator_runtime(
        project_id=args.project_id,
        group_id=args.group_id,
        sandbox_id=args.sandbox_id,
        pending_id=args.pending_id,
        project_root=args.project_root,
        workflow_root=args.workflow_root,
        output_dir=args.output_dir,
        brain_ipc_host=args.brain_ipc_host,
        brain_ipc_port=args.brain_ipc_port,
        brain_agentctl_host=args.brain_agentctl_host,
        brain_agentctl_port=args.brain_agentctl_port,
        brain_task_manager_host=args.brain_task_manager_host,
        brain_task_manager_port=args.brain_task_manager_port,
    )


if __name__ == "__main__":
    main()
