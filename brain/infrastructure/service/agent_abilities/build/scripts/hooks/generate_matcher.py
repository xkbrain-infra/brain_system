#!/usr/bin/env python3
"""
自动从 lep.yaml 生成最优的 settings.local.json matcher 配置
"""
import yaml
import json
from pathlib import Path

LEP_FILE = Path("/brain/base/spec/core/lep.yaml")
SETTINGS_TEMPLATE = Path("/brain/.claude/settings.local.json")

def extract_tools_from_lep(stage="pre_tool_use"):
    """从 lep.yaml 中提取触发指定 stage 的所有工具"""
    with open(LEP_FILE) as f:
        lep = yaml.safe_load(f)

    tools = set()

    for gate_id, gate_spec in lep.get('gates', {}).items():
        enforcement = gate_spec.get('enforcement', {})

        if enforcement.get('stage') != stage:
            continue

        triggers = enforcement.get('triggers', {})
        gate_tools = triggers.get('tools', [])

        if gate_tools:
            tools.update(gate_tools)

    return sorted(tools)

def generate_matcher(tools):
    """生成正则表达式 matcher"""
    if not tools:
        return ".*"

    # 排除通配符
    tools = [t for t in tools if t != '*']

    if not tools:
        return ".*"

    return '|'.join(tools)

def generate_settings():
    """生成完整的 settings.local.json 配置"""

    # 提取各个 stage 的工具
    pre_tool_use_tools = extract_tools_from_lep("pre_tool_use")

    print("=== LEP Matcher 自动生成器 ===\n")
    print(f"从 {LEP_FILE} 提取规则\n")

    print(f"📍 PreToolUse 触发的工具: {len(pre_tool_use_tools)} 个")
    for tool in pre_tool_use_tools:
        print(f"   - {tool}")
    print()

    matcher = generate_matcher(pre_tool_use_tools)
    print(f"生成的 Matcher: {matcher}\n")

    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                            "description": f"LEP Engine - {len(pre_tool_use_tools)} 个工具触发 pre_tool_use 规则"
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/post_tool_use",
                            "description": "LEP Engine - 审计日志"
                        }
                    ]
                }
            ]
        }
    }

    return settings

if __name__ == "__main__":
    settings = generate_settings()

    print("=== 生成的配置 ===\n")
    print(json.dumps(settings, indent=2))

    # 可选：写入文件
    output_file = Path("/brain/.claude/settings.local.json.generated")
    with open(output_file, 'w') as f:
        json.dump(settings, f, indent=2)

    print(f"\n✅ 配置已生成: {output_file}")
    print(f"\n要启用此配置，请运行:")
    print(f"  cp {output_file} /brain/.claude/settings.local.json")
