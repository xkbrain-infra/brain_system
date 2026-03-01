#!/usr/bin/env python3
"""
generate_stats.py — 生成 spec/lep/hooks 覆盖统计
同时输出两个文件：
  spec_stats.yaml  — 机器可读，供构建流水线使用
  spec_stats.md    — Markdown 表格，供人/LLM 阅读
用法: python3 generate_stats.py <src_base_dir> <output_dir>
"""
import yaml, os, sys
from collections import defaultdict
from datetime import datetime, timezone


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def md_table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    def fmt_row(r):
        return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) + " |"
    sep = "|-" + "-|-".join("-" * w for w in widths) + "-|"
    return "\n".join([fmt_row(headers), sep] + [fmt_row(r) for r in rows])


def update_registry(registry_path, doc_id, output_dir, today):
    reg = load_yaml(registry_path)
    docs = reg["registry"]["documents"]
    is_new = doc_id not in docs
    docs[doc_id] = {
        "id": doc_id,
        "scope": "G",
        "title": "Spec / LEP / Hooks 覆盖统计索引",
        "path": "/brain/base/knowledge/brian_system/spec/spec_stats.md",
        "category": "GUIDE",
        "tags": ["spec", "lep", "hooks", "stats", "auto_generated"],
        "last_modified": today,
        "description": "由 build stats 自动生成 — spec 文档分类数、LEP gates 分布、hooks 覆盖率",
        "load_triggers": ["spec统计", "lep覆盖", "hooks覆盖", "spec_stats"],
    }
    if is_new:
        reg["registry"]["meta"]["total_documents"] += 1
    reg["registry"]["meta"]["last_updated"] = today
    save_yaml(registry_path, reg)
    return is_new


def update_knowledge_index(index_path, today):
    idx = load_yaml(index_path)
    structure = idx.get("structure", {})
    if "brian_system/" not in structure:
        structure["brian_system/"] = {
            "_index.yaml": "目录索引",
            "spec/spec_stats.yaml": "Spec/LEP/Hooks 覆盖统计 YAML（build stats 自动生成）",
            "spec/spec_stats.md": "Spec/LEP/Hooks 覆盖统计 Markdown（build stats 自动生成）",
        }
        idx["structure"] = structure
    ql = idx.get("quick_lookup", {})
    for kw in ["spec统计", "lep覆盖", "hooks覆盖", "spec_stats"]:
        ql[kw] = "brian_system/spec/spec_stats.md"
    idx["quick_lookup"] = ql
    save_yaml(index_path, idx)


def write_yaml(output_path, spec_by_cat, lep_by_cat, universal, all_gate_ids,
               hooks_covered, hooks_not_covered, total_docs, total_gates,
               n_covered, coverage, now, today):
    """生成机器可读的 YAML 统计文件"""
    data = {
        "id": "G-KNLG-BRIAN-SYSTEM-SPEC-STATS",
        "title": "Spec / LEP / Hooks 覆盖统计索引",
        "generated_at": now,
        "last_updated": today,
        "spec": {
            "total": total_docs,
            "by_category": {
                cat: {
                    "count": len(doc_list),
                    "ids": [doc_id for doc_id, _ in sorted(doc_list, key=lambda x: x[0])],
                }
                for cat, doc_list in sorted(spec_by_cat.items())
            },
        },
        "lep": {
            "total": total_gates,
            "universal_count": len(universal & all_gate_ids),
            "universal_gates": sorted(universal & all_gate_ids),
            "by_category": {
                cat: {
                    "count": len(gate_list),
                    "ids": [g["id"] for g in sorted(gate_list, key=lambda g: g["id"])],
                }
                for cat, gate_list in sorted(lep_by_cat.items())
            },
        },
        "hooks": {
            "covered": n_covered,
            "total": total_gates,
            "coverage_pct": coverage,
            "covered_gates": [
                {
                    "gate_id": gid,
                    "method": method,
                    "universal": gid in universal,
                }
                for gid, method, _, _ in sorted(hooks_covered)
            ],
            "not_covered_gates": [
                {
                    "gate_id": gid,
                    "method": method,
                    "universal": gid in universal,
                    "reason": method or "无 enforcement",
                }
                for gid, method, _, _ in sorted(hooks_not_covered)
            ],
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    save_yaml(output_path, data)


def write_markdown(output_path, spec_by_cat, lep_by_cat, universal, all_gate_ids,
                   hooks_covered, hooks_not_covered, gate_rules, total_docs, total_gates,
                   n_covered, coverage, now, today):
    """生成人/LLM 可读的 Markdown 统计文件"""
    lines = []
    lines.append("# Spec / LEP / Hooks 覆盖统计")
    lines.append("")
    lines.append(f"> 自动生成 by `build.sh stats` · {now}")
    lines.append("")

    # ── 摘要 ─────────────────────────────────────────────────
    lines.append("## 摘要")
    lines.append("")
    lines.append(md_table(
        ["指标", "数值"],
        [
            ["Spec 文档总数", total_docs],
            ["LEP gates 总数", total_gates],
            ["LEP universal gates", len(universal & all_gate_ids)],
            ["Hooks 覆盖 gates", f"{n_covered}/{total_gates} ({coverage}%)"],
        ]
    ))
    lines.append("")

    # ── Spec 文档（按分类） ───────────────────────────────────
    lines.append("## Spec 文档（按分类）")
    lines.append("")
    for cat, doc_list in sorted(spec_by_cat.items()):
        lines.append(f"### {cat}（{len(doc_list)}）")
        lines.append("")
        rows = []
        for doc_id, doc in sorted(doc_list, key=lambda x: x[0]):
            path = doc.get("path", "")
            rows.append([doc_id, doc.get("description", ""), path])
        lines.append(md_table(["ID", "Rule", "路径"], rows))
        lines.append("")

    # ── LEP Gates（按分类） ──────────────────────────────────
    lines.append("## LEP Gates（按分类）")
    lines.append("")
    for cat, gate_list in sorted(lep_by_cat.items()):
        lines.append(f"### {cat}（{len(gate_list)}）")
        lines.append("")
        rows = []
        for gate in sorted(gate_list, key=lambda g: g["id"]):
            gid  = gate["id"]
            u    = "✓" if gid in universal else ""
            file = gate.get("file", "")
            path = f"policies/lep/{file}" if file else ""
            rows.append([gid, gate_rules.get(gid, ""), u, path])
        lines.append(md_table(["Gate ID", "Rule", "Universal", "路径"], rows))
        lines.append("")

    # ── Hooks 覆盖 ────────────────────────────────────────────
    lines.append(f"## Hooks 覆盖（{n_covered}/{total_gates} = {coverage}%）")
    lines.append("")
    lines.append(f"### 已覆盖（{n_covered}）")
    lines.append("")
    rows = [(gid, method, u, path) for gid, method, u, path in sorted(hooks_covered)]
    lines.append(md_table(["Gate ID", "Method", "Universal", "路径"], rows))
    lines.append("")
    lines.append(f"### 未覆盖（{len(hooks_not_covered)}）")
    lines.append("")
    rows = [(gid, method or "无 enforcement", u, path) for gid, method, u, path in sorted(hooks_not_covered)]
    lines.append(md_table(["Gate ID", "原因/Method", "Universal", "路径"], rows))
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def main():
    src_base   = sys.argv[1]
    output_dir = sys.argv[2]

    spec_dir = os.path.join(src_base, "spec")
    lep_dir  = os.path.join(spec_dir, "policies", "lep")
    knlg_dir = os.path.join(src_base, "knowledge")

    # ── Spec 文档统计 ─────────────────────────────────────────
    reg  = load_yaml(os.path.join(spec_dir, "registry.yaml"))
    docs = reg["registry"]["documents"]
    spec_by_cat = defaultdict(list)
    for doc_id, doc in docs.items():
        spec_by_cat[doc.get("category", "UNKNOWN")].append((doc_id, doc))

    # ── LEP gates ─────────────────────────────────────────────
    lep_core     = load_yaml(os.path.join(spec_dir, "core", "lep.yaml"))
    universal    = set(lep_core.get("universal_gates", {}).keys())
    lep_idx      = load_yaml(os.path.join(lep_dir, "index.yaml"))
    domain_gates = lep_idx.get("gates", [])
    all_gate_ids = {g["id"] for g in domain_gates}

    lep_by_cat = defaultdict(list)
    for gate in domain_gates:
        lep_by_cat[gate.get("category", "UNKNOWN")].append(gate)

    # ── 读 gate 文件：hooks 覆盖 + rule 首行 ─────────────────
    SUPPORTED = {"python_inline", "python_checker", "c_binary", "python_logger"}
    hooks_covered     = []
    hooks_not_covered = []
    gate_rules        = {}   # gate_id → rule 首行（供 LEP 表格用）

    for fname in sorted(os.listdir(lep_dir)):
        if not fname.endswith(".yaml") or fname in ("index.yaml", "validators.yaml"):
            continue
        data = load_yaml(os.path.join(lep_dir, fname))
        if not data:
            continue
        gid    = data.get("gate_id", data.get("id", fname))
        enf    = data.get("enforcement", {})
        method = enf.get("method", "") if enf else ""
        path   = data.get("detail", f"policies/lep/{fname}")
        rule   = str(data.get("rule", "")).strip().splitlines()[0] if data.get("rule") else ""
        gate_rules[gid] = rule
        entry  = (gid, method, "✓" if gid in universal else "", path)
        if method in SUPPORTED:
            hooks_covered.append(entry)
        else:
            hooks_not_covered.append(entry)

    total_gates = len(domain_gates)
    total_docs  = len(docs)
    n_covered   = len(hooks_covered)
    coverage    = round(n_covered / total_gates * 100) if total_gates else 0

    now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 输出文件路径 ──────────────────────────────────────────
    yaml_out = os.path.join(output_dir, "spec_stats.yaml")
    md_out   = os.path.join(output_dir, "spec_stats.md")

    # ── 写 YAML ───────────────────────────────────────────────
    write_yaml(yaml_out, spec_by_cat, lep_by_cat, universal, all_gate_ids,
               hooks_covered, hooks_not_covered, total_docs, total_gates,
               n_covered, coverage, now, today)

    # ── 写 Markdown ───────────────────────────────────────────
    write_markdown(md_out, spec_by_cat, lep_by_cat, universal, all_gate_ids,
                   hooks_covered, hooks_not_covered, gate_rules, total_docs, total_gates,
                   n_covered, coverage, now, today)

    # ── 更新 registry + index ─────────────────────────────────
    is_new = update_registry(os.path.join(knlg_dir, "registry.yaml"),
                             "G-KNLG-BRIAN-SYSTEM-SPEC-STATS", output_dir, today)
    update_knowledge_index(os.path.join(knlg_dir, "index.yaml"), today)

    print(f"[stats] yaml → {yaml_out}")
    print(f"[stats] md   → {md_out}")
    print(f"[stats] registry: {'registered (new)' if is_new else 'updated'}")
    print(f"  spec:  {total_docs}  (CORE:{len(spec_by_cat.get('CORE',[]))} POLICY:{len(spec_by_cat.get('POLICY',[]))} STANDARD:{len(spec_by_cat.get('STANDARD',[]))} TEMPLATE:{len(spec_by_cat.get('TEMPLATE',[]))})")
    print(f"  lep:   {total_gates} gates  (universal:{len(universal & all_gate_ids)})")
    print(f"  hooks: {n_covered}/{total_gates} ({coverage}%)")


if __name__ == "__main__":
    main()
