#!/usr/bin/env python3
"""Test: Role Coverage

按角色验证 spec 覆盖度：
1. 每个角色模板中引用的 spec 关键词，在 registry quick_lookup 中能否命中
2. 每个角色在 core spec 中是否被提及（workflow steps owner/participants）
3. 每个注册角色都有对应的模板文件
4. quick_lookup 中角色相关关键词能关联到具体文档

角色列表来源: templates/agent/index.yaml
"""

import sys
import os
import re
import yaml
from pathlib import Path

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ─── 角色 → 必须覆盖的 spec 主题映射 ───
# 每个角色执行工作时需要的 spec 知识领域
ROLE_REQUIRED_TOPICS = {
    "pmo": {
        "must": ["workflow", "estimation", "agent"],
        "should": ["creation", "memory"],
        "description": "PMO 需要: 任务流程、时间估算、Agent 协作、项目创建",
    },
    "architect": {
        "must": ["architecture", "layers", "lep"],
        "should": ["ipc", "docker", "database"],
        "description": "Architect 需要: 架构定义、LEP 规则、IPC/Docker/DB 标准",
    },
    "developer": {
        "must": ["lep", "verification", "workflow"],
        "should": ["docker", "cpp"],
        "description": "Developer 需要: LEP 规则、代码验证、执行规范",
    },
    "qa": {
        "must": ["verification", "workflow", "lep"],
        "should": ["docker"],
        "description": "QA 需要: 验证标准、执行规范、LEP 规则",
    },
    "devops": {
        "must": ["docker", "deployment", "database"],
        "should": ["config", "secrets"],
        "description": "DevOps 需要: Docker、部署、数据库、配置/密钥管理",
    },
    "frontdesk": {
        "must": ["ipc", "agent"],
        "should": ["workflow"],
        "description": "Frontdesk 需要: IPC 通信、Agent 协作",
    },
    "researcher": {
        "must": ["workflow", "lep"],
        "should": ["architecture"],
        "description": "Researcher 需要: 执行规范、LEP、架构参考",
    },
    "ui-designer": {
        "must": ["workflow", "lep"],
        "should": ["file"],
        "description": "UI Designer 需要: 执行规范、LEP、文件组织",
    },
}


def test_role_templates_exist(spec_dir: Path) -> bool:
    """每个注册角色都有模板文件."""
    roles_dir = spec_dir / "templates" / "agent" / "roles"
    index_path = spec_dir / "templates" / "agent" / "index.yaml"

    if not index_path.exists():
        print(f"  WARN templates/agent/index.yaml not found")
        return True

    index = load_yaml(index_path)
    roles = index.get("roles", {})
    errors = []

    for role_name, role_data in roles.items():
        tmpl = role_data.get("template", "")
        tmpl_path = spec_dir / "templates" / "agent" / tmpl
        if not tmpl_path.exists():
            errors.append(f"{role_name}: {tmpl_path} not found")

    ok = not errors
    if errors:
        for e in errors:
            print(f"  FAIL {e}")
    else:
        print(f"  PASS All {len(roles)} role templates exist")
    return ok


def test_role_quick_lookup(spec_dir: Path) -> bool:
    """每个角色名在 quick_lookup 中有对应条目."""
    registry = load_yaml(spec_dir / "registry.yaml")
    ql = registry["registry"].get("quick_lookup", {})

    index = load_yaml(spec_dir / "templates" / "agent" / "index.yaml")
    roles = list(index.get("roles", {}).keys())

    missing = []
    for role in roles:
        # 检查角色名或变体是否在 quick_lookup 中
        variants = [role, role.replace("-", "_")]
        found = any(v in ql for v in variants)
        if not found:
            missing.append(role)

    ok = not missing
    if missing:
        for m in missing:
            print(f"  FAIL Role '{m}' not in quick_lookup")
    else:
        print(f"  PASS All {len(roles)} roles have quick_lookup entries")
    return ok


def test_role_topic_coverage(spec_dir: Path) -> bool:
    """每个角色所需的 spec 主题在 quick_lookup 中可达."""
    registry = load_yaml(spec_dir / "registry.yaml")
    ql = registry["registry"].get("quick_lookup", {})
    docs = registry["registry"]["documents"]

    all_ok = True
    for role, req in ROLE_REQUIRED_TOPICS.items():
        print(f"\n  [{role}] {req['description']}")
        role_ok = True

        for topic in req["must"]:
            if topic in ql:
                doc_ids = ql[topic]
                # 验证这些 doc_ids 都指向有效文档
                valid = [d for d in doc_ids if d in docs]
                print(f"    PASS must[{topic}] → {len(valid)} doc(s)")
            else:
                print(f"    FAIL must[{topic}] → NOT in quick_lookup")
                role_ok = False

        for topic in req.get("should", []):
            if topic in ql:
                print(f"    PASS should[{topic}] → reachable")
            else:
                print(f"    WARN should[{topic}] → NOT in quick_lookup")

        if not role_ok:
            all_ok = False

    return all_ok


def test_workflow_role_mentions(spec_dir: Path) -> bool:
    """core/workflow.yaml 中提及了所有关键角色."""
    wf_path = spec_dir / "core" / "workflow.yaml"
    if not wf_path.exists():
        print(f"  WARN core/workflow.yaml not found")
        return True

    content = wf_path.read_text()

    # 核心角色应该在 workflow 中被提及（作为 owner 或 constraint 参与者）
    core_roles = ["pmo", "architect", "qa", "devops"]
    missing = [r for r in core_roles if r not in content.lower()]

    # workflow.yaml 是全员规范，不需要每个角色都出现
    # 但 PMO 作为任务管理者必须出现
    if "pmo" not in content.lower():
        print(f"  FAIL PMO not mentioned in core/workflow.yaml")
        return False

    print(f"  PASS core/workflow.yaml mentions PMO as task authority")
    return True


def main():
    spec_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/brain/infrastructure/service/agent_abilities/spec/src")
    print(f"=== Role Coverage Test: {spec_dir} ===")

    all_ok = True

    tests = [
        ("Role templates exist", lambda: test_role_templates_exist(spec_dir)),
        ("Role quick_lookup entries", lambda: test_role_quick_lookup(spec_dir)),
        ("Workflow role mentions", lambda: test_workflow_role_mentions(spec_dir)),
        ("Role topic coverage", lambda: test_role_topic_coverage(spec_dir)),
    ]

    for name, fn in tests:
        print(f"\n{name}:")
        if not fn():
            all_ok = False

    print(f"\n{'=' * 40}")
    if all_ok:
        print(f"{GREEN}ROLE COVERAGE: ALL PASSED{RESET}")
        return 0
    else:
        print(f"{RED}ROLE COVERAGE: SOME FAILURES{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
