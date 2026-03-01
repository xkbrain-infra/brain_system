#!/usr/bin/env python3
"""
Settings.json 生成器
功能：根据合并后的规则生成 settings.json 模板
"""
import yaml
import json
from pathlib import Path
from collections import defaultdict

HOOK_ROOT = Path("/brain/infrastructure/service/agent_abilities")
BUILD_DIR = HOOK_ROOT / "build"

def extract_tools_from_lep(lep_file):
    """从 lep.yaml 中提取触发 pre_tool_use 的所有工具"""
    with open(lep_file) as f:
        lep = yaml.safe_load(f)

    tools = set()

    for gate_id, gate_spec in lep.get('gates', {}).items():
        enforcement = gate_spec.get('enforcement', {})

        if enforcement.get('stage') != 'pre_tool_use':
            continue

        triggers = enforcement.get('triggers', {})
        gate_tools = triggers.get('tools', [])

        if gate_tools:
            tools.update(gate_tools)

    # 排除通配符
    tools = {t for t in tools if t != '*'}

    return sorted(tools)

def generate_matcher(tools):
    """生成正则表达式 matcher"""
    if not tools:
        return ".*"
    return '|'.join(tools)

def generate_settings_for_role(role, lep_file, bin_path):
    """为特定角色生成 settings.json"""

    # 提取工具
    tools = extract_tools_from_lep(lep_file)
    matcher = generate_matcher(tools)

    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(bin_path / "pre_tool_use"),
                            "description": f"LEP Engine - {role} role ({len(tools)} tools)"
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
                            "command": str(bin_path / "post_tool_use"),
                            "description": "LEP Engine - Audit logging"
                        }
                    ]
                }
            ]
        },
        "permissions": {
            "defaultMode": "bypassPermissions"
        }
    }

    return settings, tools

def main():
    print("生成 settings.json 模板...")

    # 生成全局配置
    print("\n生成全局配置...")
    global_lep = Path("/brain/base/spec/core/lep.yaml")
    bin_path = Path("/brain/infrastructure/service/agent_abilities/hooks/bin/current")

    global_settings, global_tools = generate_settings_for_role("global", global_lep, bin_path)

    output_file = BUILD_DIR / "configs" / "settings.global.json"
    with open(output_file, 'w') as f:
        json.dump(global_settings, f, indent=2, ensure_ascii=False)

    print(f"  ✓ 全局配置: {len(global_tools)} 个工具")
    print(f"  Matcher: {generate_matcher(global_tools)}")
    print(f"  保存到: {output_file}")

    # 生成角色配置
    roles = ['pmo', 'architect', 'dev', 'qa']

    for role in roles:
        print(f"\n生成 {role} 配置...")

        lep_file = BUILD_DIR / "configs" / "merged_rules" / f"lep.{role}.yaml"

        if not lep_file.exists():
            print(f"  ⚠️  规则文件不存在，跳过")
            continue

        settings, tools = generate_settings_for_role(role, lep_file, bin_path)

        output_file = BUILD_DIR / "configs" / "settings.roles" / f"settings.{role}.json"
        with open(output_file, 'w') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

        print(f"  ✓ {role} 配置: {len(tools)} 个工具")
        print(f"  Matcher: {generate_matcher(tools)}")
        print(f"  保存到: {output_file}")

    print("\n✅ 所有 settings.json 模板生成完成")

    # 统计信息
    print("\n" + "="*50)
    print("产物统计:")
    print("="*50)

    global_count = len(list((BUILD_DIR / "configs").glob("settings.global.json")))
    role_count = len(list((BUILD_DIR / "configs" / "settings.roles").glob("settings.*.json")))

    print(f"全局配置: {global_count} 个")
    print(f"角色配置: {role_count} 个")
    print()

if __name__ == "__main__":
    main()
