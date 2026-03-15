#!/usr/bin/env python3
"""
Agent 状态监控
监控所有注册的 Agent 在线状态和心跳
"""

import json
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Any


def get_registered_agents() -> List[Dict[str, Any]]:
    """获取所有注册的 Agent 列表"""
    # 简化实现：读取 daemon 状态文件或 registry
    # 如果 daemon 有 state 文件，从那里读取
    # 否则返回示例数据供测试

    # TODO: 实际实现需要调用 IPC daemon API
    # 这里提供一个基础实现，通过检查已知的 agent session 路径

    agents = []

    # 从环境变量或配置文件读取 agent 列表
    # 作为 MVP，先返回硬编码的核心 agents
    core_agents = [
        'agent_xkquant_pmo',
        'agent_xkquant_devops',
        'agent_xkquant_architect',
        'agent_system_frontdesk',
        'agent_system_timer'
    ]

    for agent_name in core_agents:
        agents.append({
            'name': agent_name,
            'status': 'online',  # 简化假设都在线
            'last_heartbeat': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'metadata': {}
        })

    return agents


def format_agent_status(agents: List[Dict[str, Any]]) -> str:
    """格式化 Agent 状态输出"""
    if not agents:
        return "No agents registered."

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Agent Status Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"{'='*80}\n")

    # 按状态分组
    online = [a for a in agents if a.get('status') == 'online']
    offline = [a for a in agents if a.get('status') != 'online']

    output.append(f"Summary: {len(online)} online, {len(offline)} offline\n")

    # 在线 Agents
    if online:
        output.append("ONLINE AGENTS:")
        output.append(f"{'Name':<30} {'Status':<10} {'Last Seen':<20} {'Metadata'}")
        output.append("-" * 80)

        for agent in sorted(online, key=lambda x: x.get('name', '')):
            name = agent.get('name', 'unknown')
            status = agent.get('status', 'unknown')
            last_seen = agent.get('last_heartbeat', 'N/A')
            metadata = agent.get('metadata', {})

            # 简化 metadata 显示
            meta_str = json.dumps(metadata) if metadata else ''
            if len(meta_str) > 30:
                meta_str = meta_str[:27] + '...'

            output.append(f"{name:<30} {status:<10} {last_seen:<20} {meta_str}")

    # 离线 Agents
    if offline:
        output.append("\nOFFLINE AGENTS:")
        for agent in sorted(offline, key=lambda x: x.get('name', '')):
            output.append(f"  - {agent.get('name', 'unknown')}")

    output.append("\n" + "="*80 + "\n")
    return "\n".join(output)


def main():
    """主函数"""
    agents = get_registered_agents()
    print(format_agent_status(agents))


if __name__ == '__main__':
    main()
