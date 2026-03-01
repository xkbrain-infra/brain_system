#!/usr/bin/env python3
"""
高级 Matcher 生成器 - 支持多种优化策略
"""
import yaml
import json
from pathlib import Path
from collections import defaultdict

LEP_FILE = Path("/brain/base/spec/core/lep.yaml")

def analyze_lep():
    """分析 lep.yaml，提取工具和规则的映射关系"""
    with open(LEP_FILE) as f:
        lep = yaml.safe_load(f)

    tool_gates = defaultdict(list)
    tool_priority_count = defaultdict(lambda: defaultdict(int))

    for gate_id, gate_spec in lep.get('gates', {}).items():
        enforcement = gate_spec.get('enforcement', {})
        stage = enforcement.get('stage', '')

        if stage != 'pre_tool_use':
            continue

        triggers = enforcement.get('triggers', {})
        tools = triggers.get('tools', [])
        priority = enforcement.get('priority', 'MEDIUM')

        if not tools:
            tools = ['*']

        for tool in tools:
            tool_gates[tool].append({
                'gate_id': gate_id,
                'priority': priority
            })
            tool_priority_count[tool][priority] += 1

    return tool_gates, tool_priority_count

def generate_simple_strategy():
    """策略 1: 单一 Matcher（所有工具）"""
    return {
        "name": "Simple (All Tools)",
        "description": "所有工具都进入 hook，LepEngine 内部过滤",
        "config": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{
                            "type": "command",
                            "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use"
                        }]
                    }
                ]
            }
        },
        "pros": ["配置简单", "不会遗漏新规则"],
        "cons": ["所有工具都触发 hook（包括不相关的）", "性能开销较大"]
    }

def generate_precise_strategy(tool_gates):
    """策略 2: 精确 Matcher（只匹配有规则的工具）"""
    tools = sorted([t for t in tool_gates.keys() if t != '*'])
    matcher = '|'.join(tools) if tools else '.*'

    return {
        "name": "Precise (Only Relevant Tools)",
        "description": f"只匹配有规则的 {len(tools)} 个工具",
        "config": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": matcher,
                        "hooks": [{
                            "type": "command",
                            "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                            "description": f"LEP Engine - {len(tools)} 个工具触发"
                        }]
                    }
                ]
            }
        },
        "pros": ["性能最优", "不相关的工具直接跳过"],
        "cons": ["添加新规则时需要重新生成 matcher"]
    }

def generate_tiered_strategy(tool_gates, tool_priority_count):
    """策略 3: 分层 Matcher（按规则数量分组）"""
    # 计算每个工具的规则数量
    tool_rule_count = {tool: len(gates) for tool, gates in tool_gates.items() if tool != '*'}

    # 分为高、中、低风险
    high_risk = []  # 规则数 >= 8
    medium_risk = []  # 规则数 4-7
    low_risk = []  # 规则数 1-3

    for tool, count in sorted(tool_rule_count.items(), key=lambda x: -x[1]):
        if count >= 8:
            high_risk.append(tool)
        elif count >= 4:
            medium_risk.append(tool)
        else:
            low_risk.append(tool)

    matchers = []

    if high_risk:
        matchers.append({
            "matcher": '|'.join(high_risk),
            "hooks": [{
                "type": "command",
                "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                "description": f"高风险工具: {', '.join(high_risk)} (规则数 ≥ 8)"
            }]
        })

    if medium_risk:
        matchers.append({
            "matcher": '|'.join(medium_risk),
            "hooks": [{
                "type": "command",
                "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                "description": f"中风险工具: {', '.join(medium_risk)} (规则数 4-7)"
            }]
        })

    if low_risk:
        matchers.append({
            "matcher": '|'.join(low_risk),
            "hooks": [{
                "type": "command",
                "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                "description": f"低风险工具: {', '.join(low_risk)} (规则数 1-3)"
            }]
        })

    return {
        "name": "Tiered (Risk-Based Grouping)",
        "description": "按规则数量分为高/中/低风险组",
        "config": {
            "hooks": {
                "PreToolUse": matchers
            }
        },
        "groups": {
            "high_risk": high_risk,
            "medium_risk": medium_risk,
            "low_risk": low_risk
        },
        "pros": ["逻辑清晰", "可针对不同风险级别优化"],
        "cons": ["配置较复杂", "同一 hook 被调用多次"]
    }

def generate_priority_strategy(tool_gates, tool_priority_count):
    """策略 4: 按优先级分组"""
    # 只包含 CRITICAL 规则的工具
    critical_tools = []
    other_tools = []

    for tool, counts in tool_priority_count.items():
        if tool == '*':
            continue
        if counts.get('CRITICAL', 0) > 0:
            critical_tools.append(tool)
        else:
            other_tools.append(tool)

    matchers = []

    if critical_tools:
        matchers.append({
            "matcher": '|'.join(sorted(critical_tools)),
            "hooks": [{
                "type": "command",
                "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                "description": f"包含 CRITICAL 规则的工具: {len(critical_tools)} 个"
            }]
        })

    if other_tools:
        matchers.append({
            "matcher": '|'.join(sorted(other_tools)),
            "hooks": [{
                "type": "command",
                "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
                "description": f"其他工具: {len(other_tools)} 个"
            }]
        })

    return {
        "name": "Priority-Based (Critical vs Others)",
        "description": "按是否包含 CRITICAL 规则分组",
        "config": {
            "hooks": {
                "PreToolUse": matchers
            }
        },
        "groups": {
            "critical_tools": critical_tools,
            "other_tools": other_tools
        },
        "pros": ["突出高优先级工具", "可针对 CRITICAL 规则优化"],
        "cons": ["配置复杂", "实际收益可能不大"]
    }

def print_strategy(strategy, index):
    """打印策略详情"""
    print(f"\n{'='*60}")
    print(f"策略 {index}: {strategy['name']}")
    print(f"{'='*60}")
    print(f"\n描述: {strategy['description']}\n")

    print("优点:")
    for pro in strategy.get('pros', []):
        print(f"  ✅ {pro}")

    print("\n缺点:")
    for con in strategy.get('cons', []):
        print(f"  ⚠️ {con}")

    if 'groups' in strategy:
        print(f"\n分组详情:")
        for group_name, tools in strategy['groups'].items():
            print(f"  - {group_name}: {tools}")

    print(f"\n配置:")
    print(json.dumps(strategy['config'], indent=2, ensure_ascii=False))

def main():
    print("=== LEP Matcher 高级生成器 ===\n")

    # 分析 lep.yaml
    tool_gates, tool_priority_count = analyze_lep()

    print(f"从 {LEP_FILE} 分析完成\n")
    print("工具规则统计:")
    for tool in sorted(tool_gates.keys()):
        if tool == '*':
            continue
        count = len(tool_gates[tool])
        priorities = tool_priority_count[tool]
        print(f"  - {tool:10s}: {count:2d} 个规则", end="")
        if priorities.get('CRITICAL'):
            print(f" (含 {priorities['CRITICAL']} 个 CRITICAL)", end="")
        print()

    # 生成所有策略
    strategies = [
        generate_simple_strategy(),
        generate_precise_strategy(tool_gates),
        generate_tiered_strategy(tool_gates, tool_priority_count),
        generate_priority_strategy(tool_gates, tool_priority_count),
    ]

    # 打印所有策略
    for i, strategy in enumerate(strategies, 1):
        print_strategy(strategy, i)

    # 推荐策略
    print(f"\n{'='*60}")
    print("🌟 推荐策略")
    print(f"{'='*60}")
    print("\n对于 LEP 系统，推荐使用 策略 2: Precise")
    print("理由:")
    print("  1. 性能最优（只有 6 个工具触发 hook）")
    print("  2. 配置简单（只需一个 matcher）")
    print("  3. 易于维护（可通过脚本自动生成）")

    print("\n要应用推荐策略，请运行:")
    print("  python3 /brain/infrastructure/service/agent_abilities/hooks/scripts/generate_matcher.py")
    print("  cp /brain/.claude/settings.local.json.generated /brain/.claude/settings.local.json")

if __name__ == "__main__":
    main()
