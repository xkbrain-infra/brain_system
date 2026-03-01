#!/usr/bin/env python3
"""Spec Registry Validator

校验 spec 目录的 registry.yaml 一致性：
- 所有注册路径指向真实文件
- 文档计数与实际条目匹配
- category 计数与列表长度匹配
- quick_lookup 引用的 ID 存在于 documents 中
- YAML 语法正确
- 检测未注册的孤立文件

用法:
  python3 validate.py [spec_dir]
  默认 spec_dir = /brain/infrastructure/service/agent_abilities/spec/src (开发) 或 /brain/base/spec (发布)
"""

import sys
import os
import yaml
from pathlib import Path

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def load_registry(spec_dir: Path) -> dict:
    registry_path = spec_dir / "registry.yaml"
    if not registry_path.exists():
        print(f"{RED}FATAL: registry.yaml not found at {registry_path}{RESET}")
        sys.exit(1)
    with open(registry_path) as f:
        return yaml.safe_load(f)


def check_paths_exist(documents: dict, spec_dir: Path, is_src: bool) -> list:
    """Check all registered paths point to real files."""
    errors = []
    for doc_id, doc in documents.items():
        path = doc.get("path", "")
        if is_src:
            # src mode: rewrite /brain/base/spec/... → spec_dir/...
            rel = path.replace("/brain/base/spec/", "")
            check_path = spec_dir / rel
        else:
            # published mode: path is absolute
            check_path = Path(path.replace("/brain/", "/brain/"))
        if not check_path.exists():
            errors.append(f"  {doc_id}: {path} → {check_path} NOT FOUND")
    return errors


def check_meta_counts(registry: dict) -> list:
    """Check meta.total_documents matches actual entries."""
    errors = []
    meta = registry["registry"]["meta"]
    documents = registry["registry"]["documents"]
    declared = meta.get("total_documents", 0)
    actual = len(documents)
    if declared != actual:
        errors.append(f"  meta.total_documents={declared} but actual entries={actual}")
    return errors


def check_category_counts(registry: dict) -> list:
    """Check each category count matches its document list length."""
    errors = []
    categories = registry["registry"].get("categories", {})
    for cat_name, cat_data in categories.items():
        declared = cat_data.get("count", 0)
        actual = len(cat_data.get("documents", []))
        if declared != actual:
            errors.append(f"  {cat_name}: count={declared} but listed={actual}")
    return errors


def check_quick_lookup(registry: dict) -> list:
    """Check all IDs in quick_lookup exist in documents."""
    errors = []
    documents = registry["registry"]["documents"]
    quick_lookup = registry["registry"].get("quick_lookup", {})
    for keyword, doc_ids in quick_lookup.items():
        for doc_id in doc_ids:
            if doc_id not in documents:
                errors.append(f"  quick_lookup[{keyword}] references unknown ID: {doc_id}")
    return errors


def check_yaml_syntax(spec_dir: Path) -> list:
    """Check all .yaml files parse without errors."""
    errors = []
    for yaml_file in spec_dir.rglob("*.yaml"):
        try:
            with open(yaml_file) as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            errors.append(f"  {yaml_file}: {e}")
    return errors


def check_orphan_files(documents: dict, spec_dir: Path, is_src: bool) -> list:
    """Find files in policies/standards that are not registered.

    Excludes:
    - index.yaml files (directory indexes, not standalone documents)
    - policies/lep/*.yaml (managed by lep/index.yaml, not individually registered)
    """
    registered_paths = set()
    for doc in documents.values():
        path = doc.get("path", "")
        rel = path.replace("/brain/base/spec/", "")
        registered_paths.add(rel)

    # Patterns that are managed by parent index, not individually registered
    managed_patterns = [
        "policies/lep/",      # LEP gates managed by lep/index.yaml
    ]
    index_files = {"index.yaml"}

    orphans = []
    scan_dirs = ["policies", "standards"]
    for scan_dir in scan_dirs:
        full_dir = spec_dir / scan_dir
        if not full_dir.exists():
            continue
        for f in full_dir.rglob("*"):
            if f.is_file() and f.suffix in (".yaml", ".md"):
                rel = str(f.relative_to(spec_dir))
                if rel in registered_paths:
                    continue
                if f.name in index_files:
                    continue
                if any(rel.startswith(p) for p in managed_patterns):
                    continue
                orphans.append(f"  {rel} (not in registry)")

    return orphans


def main():
    if len(sys.argv) > 1:
        spec_dir = Path(sys.argv[1])
    else:
        # Default: try src first, then base/spec
        src = Path("/brain/infrastructure/service/agent_abilities/spec/src")
        if src.exists():
            spec_dir = src
        else:
            spec_dir = Path("/brain/base/spec")

    is_src = "infrastructure/spec/src" in str(spec_dir)
    mode = "SRC (dev)" if is_src else "PUBLISHED"
    print(f"Validating: {spec_dir} [{mode}]")
    print("=" * 60)

    registry = load_registry(spec_dir)
    documents = registry["registry"]["documents"]
    all_ok = True

    checks = [
        ("Registry paths exist", lambda: check_paths_exist(documents, spec_dir, is_src)),
        ("Meta document count", lambda: check_meta_counts(registry)),
        ("Category counts", lambda: check_category_counts(registry)),
        ("Quick lookup references", lambda: check_quick_lookup(registry)),
        ("YAML syntax", lambda: check_yaml_syntax(spec_dir)),
        ("Orphan files", lambda: check_orphan_files(documents, spec_dir, is_src)),
    ]

    for name, check_fn in checks:
        errors = check_fn()
        if errors:
            print(f"{RED}FAIL{RESET} {name}:")
            for e in errors:
                print(e)
            all_ok = False
        else:
            print(f"{GREEN}OK{RESET}   {name}")

    print("=" * 60)
    if all_ok:
        print(f"{GREEN}ALL CHECKS PASSED{RESET} ({len(documents)} documents)")
        return 0
    else:
        print(f"{RED}VALIDATION FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
