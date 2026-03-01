#!/usr/bin/env python3
"""Test: Spec ID Coverage

从 Agent 实际启动视角，测量所有 spec-id 的可达性。

路径层级：
  Layer 0: INIT.yaml activation_sequence 直接加载的文件
  Layer 1: CLAUDE.md 预加载的 quick_lookup 索引（所有关键词 → spec-id 映射）
  Layer 2: INIT.yaml auto_load.keywords 关键词触发
  Layer 3: 各角色模板 → 角色必需主题 → quick_lookup → spec-id
  Layer 4: registry.yaml 中注册但未被以上层级触达的 spec-id

输出：
  - 总 spec-id 数量
  - 每层覆盖的 spec-id
  - 每个角色的覆盖率
  - 未覆盖的 spec-id 清单
"""

import sys
import os
import re
import yaml
from pathlib import Path
from collections import defaultdict

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ─── 角色 → 关键词映射（与 test_role_coverage.py 保持一致）───
ROLE_KEYWORDS = {
    "pmo": ["workflow", "estimation", "agent", "creation", "memory"],
    "architect": ["architecture", "layers", "lep", "ipc", "docker", "database"],
    "developer": ["lep", "verification", "workflow", "docker", "cpp"],
    "qa": ["verification", "workflow", "lep", "docker"],
    "devops": ["docker", "deployment", "database", "config", "secrets"],
    "frontdesk": ["ipc", "agent", "workflow"],
    "researcher": ["workflow", "lep", "architecture"],
    "ui-designer": ["workflow", "lep", "file", "ui"],
}


def collect_all_spec_ids(spec_dir: Path) -> set:
    """从 registry.yaml 收集所有 spec-id."""
    registry = load_yaml(spec_dir / "registry.yaml")
    return set(registry.get("registry", {}).get("documents", {}).keys())


def collect_init_direct(spec_dir: Path) -> set:
    """Layer 0: INIT.yaml activation_sequence 直接加载的文件 → 对应的 spec-id."""
    init = load_yaml(Path("/brain/INIT.yaml"))
    registry = load_yaml(spec_dir / "registry.yaml")
    docs = registry.get("registry", {}).get("documents", {})

    # Build path → id lookup
    path_to_id = {}
    for doc_id, doc in docs.items():
        path_to_id[doc["path"]] = doc_id

    covered = set()
    # activation_sequence
    for step in init.get("activation_sequence", {}).values():
        load_path = step.get("load", "") if isinstance(step, dict) else step
        if load_path in path_to_id:
            covered.add(path_to_id[load_path])

    # core_refs
    for ref_path in init.get("core_refs", {}).values():
        if isinstance(ref_path, str) and ref_path in path_to_id:
            covered.add(path_to_id[ref_path])

    return covered


def collect_quick_lookup_reachable(spec_dir: Path) -> set:
    """Layer 1: CLAUDE.md 预加载的 quick_lookup 索引覆盖的所有 spec-id."""
    registry = load_yaml(spec_dir / "registry.yaml")
    ql = registry.get("registry", {}).get("quick_lookup", {})
    covered = set()
    for ids in ql.values():
        covered.update(ids)
    return covered


def collect_init_keywords(spec_dir: Path) -> set:
    """Layer 2: INIT.yaml auto_load.keywords 映射的关键词 → quick_lookup → spec-id."""
    init = load_yaml(Path("/brain/INIT.yaml"))
    registry = load_yaml(spec_dir / "registry.yaml")
    ql = registry.get("registry", {}).get("quick_lookup", {})

    covered = set()
    keywords_map = init.get("auto_load", {}).get("keywords", {})
    for topic, trigger_words in keywords_map.items():
        # topic 本身也查 quick_lookup
        if topic in ql:
            covered.update(ql[topic])
    return covered


def collect_role_coverage(spec_dir: Path) -> dict:
    """Layer 3: 每个角色通过关键词能触达的 spec-id."""
    registry = load_yaml(spec_dir / "registry.yaml")
    ql = registry.get("registry", {}).get("quick_lookup", {})

    role_covered = {}
    for role, keywords in ROLE_KEYWORDS.items():
        ids = set()
        for kw in keywords:
            if kw in ql:
                ids.update(ql[kw])
        role_covered[role] = ids
    return role_covered


def main():
    spec_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/brain/infrastructure/service/agent_abilities/spec/src")
    print(f"{BOLD}══════ Spec ID Coverage Report ══════{RESET}")
    print(f"Source: {spec_dir}\n")

    # ─── 收集 ───
    all_ids = collect_all_spec_ids(spec_dir)
    layer0_init = collect_init_direct(spec_dir)
    layer1_ql = collect_quick_lookup_reachable(spec_dir)
    layer2_kw = collect_init_keywords(spec_dir)
    role_coverage = collect_role_coverage(spec_dir)

    # 所有角色的并集
    all_role_ids = set()
    for ids in role_coverage.values():
        all_role_ids.update(ids)

    # 总覆盖
    total_covered = layer0_init | layer1_ql | layer2_kw | all_role_ids
    uncovered = all_ids - total_covered

    # ─── 报告 ───
    print(f"{BOLD}Total spec-ids:{RESET} {len(all_ids)}")
    print()

    # Layer 0
    print(f"{CYAN}Layer 0 — INIT activation_sequence 直接加载:{RESET}")
    print(f"  覆盖: {len(layer0_init)}/{len(all_ids)} ({100*len(layer0_init)/len(all_ids):.0f}%)")
    for sid in sorted(layer0_init):
        print(f"    {sid}")

    # Layer 1
    print(f"\n{CYAN}Layer 1 — CLAUDE.md quick_lookup 索引可达:{RESET}")
    layer1_new = layer1_ql - layer0_init
    print(f"  新增覆盖: +{len(layer1_new)} (累计 {len(layer0_init | layer1_ql)}/{len(all_ids)})")

    # Layer 2
    print(f"\n{CYAN}Layer 2 — INIT auto_load keywords 触发:{RESET}")
    layer2_new = layer2_kw - layer0_init - layer1_ql
    print(f"  新增覆盖: +{len(layer2_new)} (累计 {len(layer0_init | layer1_ql | layer2_kw)}/{len(all_ids)})")

    # Layer 3 — 角色
    print(f"\n{CYAN}Layer 3 — 角色覆盖:{RESET}")
    for role in sorted(role_coverage.keys()):
        ids = role_coverage[role]
        pct = 100 * len(ids) / len(all_ids)
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {role:15s} {bar} {len(ids):2d}/{len(all_ids)} ({pct:.0f}%)")

    # ─── 总覆盖率 ───
    total_pct = 100 * len(total_covered) / len(all_ids)
    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"{BOLD}Total coverage: {len(total_covered)}/{len(all_ids)} ({total_pct:.0f}%){RESET}")

    if uncovered:
        print(f"\n{RED}Uncovered spec-ids ({len(uncovered)}):{RESET}")
        for sid in sorted(uncovered):
            print(f"  {RED}✗{RESET} {sid}")
        print(f"\n{YELLOW}These IDs are registered but not reachable from INIT or any role.{RESET}")
        print(f"{YELLOW}Fix: add to quick_lookup, or add keywords to a role mapping.{RESET}")
    else:
        print(f"\n{GREEN}All spec-ids are reachable.{RESET}")

    print()
    # Exit code: 0 if 100%, 1 if <100%
    if total_pct >= 100:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
