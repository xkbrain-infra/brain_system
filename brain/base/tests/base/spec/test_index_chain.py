#!/usr/bin/env python3
"""Test: Index Chain Completeness

验证 spec 的索引链条完整性：
  index.yaml → registry.yaml → categories → documents → files

检查项：
1. index.yaml 引用的 registry.yaml 存在
2. registry 中每个 document ID 在 categories 中被列出
3. categories 中每个 ID 在 documents 中有定义
4. quick_lookup 中每个 ID 在 documents 中有定义
5. 所有 document 的 path 指向真实文件
6. policies/lep/index.yaml 中列出的 gate 都有对应文件
7. core/lep.yaml 中的 universal_gates 都在 lep/index.yaml 中注册
"""

import sys
import os
import yaml
from pathlib import Path

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"
PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
WARN = f"{YELLOW}WARN{RESET}"


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def resolve_path(spec_dir: Path, path: str) -> Path:
    """Convert /brain/base/spec/... path to actual filesystem path."""
    rel = path.replace("/brain/base/spec/", "")
    return spec_dir / rel


def test_index_to_registry(spec_dir: Path) -> bool:
    """index.yaml references registry.yaml which exists."""
    index = load_yaml(spec_dir / "index.yaml")
    reg_ref = index.get("registry", {}).get("file", "")
    reg_path = resolve_path(spec_dir, reg_ref) if reg_ref.startswith("/") else spec_dir / "registry.yaml"
    ok = reg_path.exists()
    print(f"  {'PASS' if ok else 'FAIL'} index.yaml → registry.yaml exists: {reg_path}")
    return ok


def test_documents_in_categories(registry: dict) -> bool:
    """Every document ID appears in exactly one category."""
    docs = registry["registry"]["documents"]
    categories = registry["registry"].get("categories", {})
    all_categorized = set()
    for cat_data in categories.values():
        all_categorized.update(cat_data.get("documents", []))

    missing = set(docs.keys()) - all_categorized
    extra = all_categorized - set(docs.keys())
    ok = not missing and not extra
    if missing:
        print(f"  FAIL Documents not in any category: {missing}")
    if extra:
        print(f"  FAIL Category refs without document entry: {extra}")
    if ok:
        print(f"  PASS All {len(docs)} documents categorized")
    return ok


def test_quick_lookup_valid(registry: dict) -> bool:
    """Every ID in quick_lookup exists in documents."""
    docs = registry["registry"]["documents"]
    ql = registry["registry"].get("quick_lookup", {})
    errors = []
    for kw, ids in ql.items():
        for doc_id in ids:
            if doc_id not in docs:
                errors.append(f"quick_lookup[{kw}] → {doc_id}")
    ok = not errors
    if errors:
        for e in errors:
            print(f"  FAIL {e} (not in documents)")
    else:
        total_refs = sum(len(v) for v in ql.values())
        print(f"  PASS quick_lookup: {len(ql)} keywords, {total_refs} refs, all valid")
    return ok


def test_document_paths(registry: dict, spec_dir: Path) -> bool:
    """Every document path points to a real file."""
    docs = registry["registry"]["documents"]
    missing = []
    for doc_id, doc in docs.items():
        p = resolve_path(spec_dir, doc["path"])
        if not p.exists():
            missing.append(f"{doc_id} → {p}")
    ok = not missing
    if missing:
        for m in missing:
            print(f"  FAIL {m}")
    else:
        print(f"  PASS All {len(docs)} document paths exist")
    return ok


def test_lep_gate_chain(spec_dir: Path) -> bool:
    """core/lep.yaml universal_gates → lep/index.yaml → gate files."""
    lep_path = spec_dir / "core" / "lep.yaml"
    idx_path = spec_dir / "policies" / "lep" / "index.yaml"
    if not lep_path.exists() or not idx_path.exists():
        print(f"  WARN lep.yaml or lep/index.yaml not found, skipping")
        return True

    lep = load_yaml(lep_path)
    idx = load_yaml(idx_path)

    # 1. Collect all gate IDs from lep.yaml (universal + domain summary)
    lep_gate_ids = set()
    for gid in lep.get("universal_gates", {}).keys():
        lep_gate_ids.add(gid)
    for gates in lep.get("domain_gates_summary", {}).values():
        lep_gate_ids.update(gates)

    # 2. Collect all gate IDs from index.yaml
    idx_gate_ids = set()
    idx_gate_files = {}
    for gate in idx.get("gates", []):
        gid = gate.get("id", "")
        idx_gate_ids.add(gid)
        idx_gate_files[gid] = gate.get("file", "")

    # 3. Check lep gates are in index
    missing_in_idx = lep_gate_ids - idx_gate_ids
    errors = []
    if missing_in_idx:
        for m in missing_in_idx:
            errors.append(f"lep.yaml declares {m} but not in lep/index.yaml")

    # 4. Check gate files exist
    lep_dir = spec_dir / "policies" / "lep"
    for gid, fname in idx_gate_files.items():
        if fname and not (lep_dir / fname).exists():
            errors.append(f"{gid} → {fname} file not found")

    ok = not errors
    if errors:
        for e in errors:
            print(f"  FAIL {e}")
    else:
        print(f"  PASS LEP chain: {len(lep_gate_ids)} gates declared, {len(idx_gate_ids)} indexed, all files exist")
    return ok


def main():
    spec_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/brain/infrastructure/service/agent_abilities/spec/src")
    print(f"=== Index Chain Test: {spec_dir} ===")

    registry = load_yaml(spec_dir / "registry.yaml")
    all_ok = True

    tests = [
        ("Index → Registry link", lambda: test_index_to_registry(spec_dir)),
        ("Documents ↔ Categories", lambda: test_documents_in_categories(registry)),
        ("Quick Lookup validity", lambda: test_quick_lookup_valid(registry)),
        ("Document paths exist", lambda: test_document_paths(registry, spec_dir)),
        ("LEP gate chain", lambda: test_lep_gate_chain(spec_dir)),
    ]

    for name, fn in tests:
        print(f"\n{name}:")
        if not fn():
            all_ok = False

    print(f"\n{'=' * 40}")
    if all_ok:
        print(f"{GREEN}INDEX CHAIN: ALL PASSED{RESET}")
        return 0
    else:
        print(f"{RED}INDEX CHAIN: FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
