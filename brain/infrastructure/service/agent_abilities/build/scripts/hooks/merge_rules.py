#!/usr/bin/env python3
"""
规则合并脚本
功能：合并全局规则 + 角色规则 → 生成角色的完整规则文件
"""
import yaml
import json
from pathlib import Path

HOOK_ROOT = Path("/brain/infrastructure/service/agent_abilities")
RULES_DIR = HOOK_ROOT / "rules"
BUILD_DIR = HOOK_ROOT / "build"

def load_yaml(file_path):
    """加载 YAML 文件"""
    if not file_path.exists():
        return {}

    with open(file_path) as f:
        return yaml.safe_load(f) or {}

def merge_rules(global_rules, role_rules):
    """合并全局规则和角色规则"""
    merged = {'gates': {}}

    # 先添加全局规则
    for gate_id, gate_spec in global_rules.get('gates', {}).items():
        merged['gates'][gate_id] = gate_spec

    # 再添加角色规则（覆盖同名规则）
    for gate_id, gate_spec in role_rules.get('gates', {}).items():
        merged['gates'][gate_id] = gate_spec

    # 合并其他字段
    for key in ['actions', 'command_mapping', 'modes']:
        if key in global_rules:
            merged[key] = global_rules[key]
        if key in role_rules:
            merged[key] = role_rules.get(key, merged.get(key, {}))

    return merged

def main():
    print("合并规则...")

    # 确保目录存在
    (BUILD_DIR / "configs" / "merged_rules").mkdir(parents=True, exist_ok=True)

    # 加载全局规则
    global_base = load_yaml(Path("/brain/base/spec/core/lep.yaml"))

    print(f"全局规则: {len(global_base.get('gates', {}))} 个 gates")

    # 处理每个角色
    roles = ['pmo', 'architect', 'dev', 'qa']

    for role in roles:
        print(f"\n处理角色: {role}")

        # 角色规则目录
        role_dir = RULES_DIR / "roles" / role

        if not role_dir.exists():
            print(f"  ⚠️  角色目录不存在，使用全局规则")
            merged = global_base
        else:
            # 加载角色的所有规则文件
            role_rules = {'gates': {}}

            for rule_file in role_dir.glob("*.yaml"):
                role_rule = load_yaml(rule_file)
                # 合并 gates
                for gate_id, gate_spec in role_rule.get('gates', {}).items():
                    role_rules['gates'][gate_id] = gate_spec

            print(f"  角色规则: {len(role_rules.get('gates', {}))} 个 gates")

            # 合并全局 + 角色
            merged = merge_rules(global_base, role_rules)

        # 保存合并结果
        output_file = BUILD_DIR / "configs" / "merged_rules" / f"lep.{role}.yaml"
        with open(output_file, 'w') as f:
            yaml.dump(merged, f, allow_unicode=True, default_flow_style=False)

        print(f"  ✓ 合并完成: {len(merged.get('gates', {}))} 个 gates")
        print(f"  保存到: {output_file}")

    print("\n✅ 所有角色规则合并完成")

if __name__ == "__main__":
    main()
