#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("publish_core.py requires PyYAML") from exc


REPO_ROOT = Path("/xkagent_infra")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CORE_MANIFEST_PATH = PROJECT_ROOT / "config" / "core_publish_manifest.yaml"
INFRA_ROUTING_PATH = PROJECT_ROOT / "config" / "infrastructure_publish_routing.yaml"


@dataclass
class Module:
    module_id: str
    kind: str
    group: str
    source_roots: list[str]
    target_roots: list[str]
    metadata: dict[str, Any]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def dump_yaml(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            sort_keys=False,
            allow_unicode=False,
            default_flow_style=False,
        )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_nested(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"missing key '{dotted_key}'")
        value = value[part]
    return value


def read_version(version_file: str | None, version_key: str | None) -> str:
    if not version_file or not version_key:
        return "workspace"
    data = load_yaml(Path(version_file))
    value = read_nested(data, version_key)
    return str(value)


def git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def module_change_summary(module: Module) -> dict[str, str]:
    paths = module.source_roots or module.target_roots
    if not paths:
        return {"status": "", "diffstat": ""}
    status = git_output(["status", "--short", "--", *paths])
    diffstat = git_output(["diff", "--stat", "--", *paths])
    return {"status": status, "diffstat": diffstat}


def run_command(
    command: list[str],
    dry_run: bool,
    activation_log: list[dict[str, Any]],
    module_id: str,
    cwd: str | None = None,
) -> None:
    entry: dict[str, Any] = {
        "module_id": module_id,
        "command": command,
        "cwd": cwd,
        "status": "dry-run" if dry_run else "running",
    }
    activation_log.append(entry)
    if dry_run:
        print("[brain_core] DRY-RUN:", " ".join(command))
        return
    print("[brain_core] RUN:", " ".join(command))
    result = subprocess.run(command, cwd=cwd, check=False, text=True)
    if result.returncode != 0:
        entry["status"] = "failed"
        entry["returncode"] = result.returncode
        raise SystemExit(result.returncode)
    entry["status"] = "ok"


def mirror_directory(
    src: Path,
    dst: Path,
    backup_root: Path,
    dry_run: bool,
    activation_log: list[dict[str, Any]],
    module_id: str,
) -> None:
    activation_log.append(
        {
            "module_id": module_id,
            "action": "mirror_directory",
            "source": str(src),
            "target": str(dst),
            "backup_root": str(backup_root),
            "status": "dry-run" if dry_run else "running",
        }
    )
    if not src.is_dir():
        activation_log[-1]["status"] = "failed"
        raise SystemExit(f"missing source directory: {src}")
    if dry_run:
        print(f"[brain_core] DRY-RUN: mirror {src} -> {dst}")
        activation_log[-1]["status"] = "dry-run"
        return
    if dst.exists():
        ensure_dir(backup_root)
        backup_target = backup_root / dst.name
        if backup_target.exists():
            shutil.rmtree(backup_target)
        shutil.copytree(dst, backup_target, symlinks=True)
    ensure_dir(dst)
    for child in dst.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target, symlinks=True)
        elif child.is_symlink():
            target.symlink_to(child.resolve())
        else:
            shutil.copy2(child, target)
    activation_log[-1]["status"] = "ok"


def verify_path(path: str) -> dict[str, Any]:
    p = Path(path)
    return {
        "check": "path_exists",
        "path": path,
        "status": "ok" if p.exists() else "missing",
    }


def verify_agent_assets(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not root.is_dir():
        results.append(
            {"check": "agents_root_exists", "path": str(root), "status": "missing"}
        )
        return results
    for agent_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for asset in [".brain", ".claude"]:
            path = agent_dir / asset
            results.append(
                {
                    "check": "agent_asset_exists",
                    "agent": agent_dir.name,
                    "path": str(path),
                    "status": "ok" if path.exists() else "missing",
                }
            )
    return results


def resolve_scope(
    scope: str,
    modules: list[Module],
    infra_routes: list[dict[str, Any]],
) -> tuple[list[Module], list[dict[str, Any]]]:
    module_by_id = {module.module_id: module for module in modules}
    core_infra = [route for route in infra_routes if route.get("core_member")]
    if scope == "all":
        selected_modules = modules
        selected_routes = core_infra
    elif scope in {"base", "platform", "runtime-assets"}:
        mapping = {
            "base": {"base_runtime"},
            "platform": {"platform_runtime"},
            "runtime-assets": {"runtime_assets"},
        }
        selected_modules = [m for m in modules if m.group in mapping[scope]]
        selected_routes = []
    elif scope in {"infrastructure", "foundation", "execution_core", "visibility", "delivery", "support"}:
        selected_modules = []
        if scope == "infrastructure":
            selected_routes = infra_routes
        else:
            selected_routes = [route for route in infra_routes if route.get("phase") == scope]
    elif scope.startswith("service:"):
        service_id = scope.split(":", 1)[1]
        selected_modules = []
        selected_routes = [route for route in infra_routes if route["service_id"] == service_id]
    elif scope.startswith("module:"):
        module_id = scope.split(":", 1)[1]
        selected_routes = []
        selected_modules = [module_by_id[module_id]] if module_id in module_by_id else []
    else:
        raise SystemExit(f"unsupported scope: {scope}")
    if not selected_modules and not selected_routes:
        raise SystemExit(f"scope produced no publish targets: {scope}")
    selected_routes.sort(key=lambda item: item.get("rollout_order", 9999))
    return selected_modules, selected_routes


def build_modules(core_manifest: dict[str, Any]) -> list[Module]:
    result: list[Module] = []
    for group_name, group_data in core_manifest["module_groups"].items():
        for entry in group_data.get("modules", []):
            result.append(
                Module(
                    module_id=entry["module_id"],
                    kind=entry["kind"],
                    group=group_name,
                    source_roots=entry.get("source_roots", []),
                    target_roots=entry.get("target_roots", []),
                    metadata=entry,
                )
            )
    return result


def verify_infra_route(route: dict[str, Any]) -> list[dict[str, Any]]:
    results = [verify_path(route["project_root"]), verify_path(route["infra_service_root"])]
    for extra_path in route.get("route_targets", {}).get("verify_paths", []):
        results.append(verify_path(extra_path))
    return results


def execute_module(
    module: Module,
    mode: str,
    backup_root: Path,
    activation_log: list[dict[str, Any]],
) -> None:
    dry_run = mode == "dry-run"
    if module.kind == "base_publish":
        command = ["bash", module.metadata["publish_script"], f"--{mode}", *module.metadata["publish_args"]]
        run_command(command, dry_run, activation_log, module.module_id)
        return
    if module.kind == "mirror_directory":
        src = Path(module.source_roots[0])
        dst = Path(module.target_roots[0])
        mirror_directory(src, dst, backup_root / module.metadata.get("backup_label", module.module_id), dry_run, activation_log, module.module_id)
        return
    if module.kind == "verify_only":
        activation_log.append(
            {
                "module_id": module.module_id,
                "action": "verify_only",
                "status": "dry-run" if dry_run else "ok",
            }
        )
        print(f"[brain_core] verify-only module: {module.module_id}")
        return
    raise SystemExit(f"unsupported module kind: {module.kind}")


def execute_infra_route(
    route: dict[str, Any],
    mode: str,
    allow_manual_gaps: bool,
    activation_log: list[dict[str, Any]],
) -> None:
    dry_run = mode == "dry-run"
    service_id = route["service_id"]
    status = route.get("implementation_status", "active")
    if status != "active":
        activation_log.append(
            {
                "module_id": service_id,
                "action": "manual_gap",
                "status": "reported",
                "reason": route.get("manual_gap_reason", status),
            }
        )
        print(f"[brain_core] manual-gap: {service_id} -> {route.get('manual_gap_reason', status)}")
        if not dry_run and route.get("core_member") and not allow_manual_gaps:
            raise SystemExit(f"blocking manual gap for core member: {service_id}")
        return
    version = read_version(route.get("version_file"), route.get("version_key"))
    driver = route["publish_driver"]
    if driver == "make_all":
        command = ["make", "-C", route["project_root"], f"VERSION={version}", "all"]
    elif driver == "make_targets":
        targets = [str(item).strip() for item in route.get("publish_targets", []) if str(item).strip()]
        if not targets:
            raise SystemExit(f"publish route {service_id} is missing publish_targets")
        command = ["make", "-C", route["project_root"], f"VERSION={version}", *targets]
    else:
        raise SystemExit(f"unsupported publish driver: {driver}")
    run_command(command, dry_run, activation_log, service_id)


def write_change_summary(path: Path, modules: list[Module], routes: list[dict[str, Any]]) -> None:
    lines = ["# Core Publish Change Summary", ""]
    for module in modules:
        summary = module_change_summary(module)
        lines.append(f"## {module.module_id}")
        lines.append("")
        lines.append(f"- kind: `{module.kind}`")
        lines.append(f"- source_roots: `{', '.join(module.source_roots)}`")
        lines.append(f"- target_roots: `{', '.join(module.target_roots)}`")
        lines.append(f"- status:")
        lines.append("```text")
        lines.append(summary["status"] or "(clean)")
        lines.append("```")
        lines.append(f"- diffstat:")
        lines.append("```text")
        lines.append(summary["diffstat"] or "(no diffstat)")
        lines.append("```")
        lines.append("")
    for route in routes:
        status = git_output(["status", "--short", "--", route["project_root"]])
        diffstat = git_output(["diff", "--stat", "--", route["project_root"]])
        lines.append(f"## {route['service_id']}")
        lines.append("")
        lines.append(f"- phase: `{route.get('phase', 'n/a')}`")
        lines.append(f"- implementation_status: `{route.get('implementation_status', 'n/a')}`")
        lines.append(f"- publish_driver: `{route.get('publish_driver', 'n/a')}`")
        lines.append(f"- publish_targets: `{json.dumps(route.get('publish_targets', []), ensure_ascii=True)}`")
        lines.append(f"- register_targets: `{json.dumps(route.get('register_targets', {}), ensure_ascii=True)}`")
        lines.append("- status:")
        lines.append("```text")
        lines.append(status or "(clean)")
        lines.append("```")
        lines.append("- diffstat:")
        lines.append("```text")
        lines.append(diffstat or "(no diffstat)")
        lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Whole-brain core publish orchestrator")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--scope",
        default="all",
        help="all|base|platform|runtime-assets|infrastructure|foundation|execution_core|visibility|delivery|support|service:<id>|module:<id>",
    )
    parser.add_argument("--allow-manual-gaps", action="store_true")
    args = parser.parse_args()

    mode = "publish" if args.publish else "dry-run"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    core_manifest = load_yaml(CORE_MANIFEST_PATH)["core_publish"]
    infra_routing = load_yaml(INFRA_ROUTING_PATH)["infrastructure_publish"]
    modules = build_modules(core_manifest)
    infra_routes = infra_routing["services"]
    selected_modules, selected_routes = resolve_scope(args.scope, modules, infra_routes)

    artifact_root = Path(core_manifest["release_artifacts_root"]) / stamp
    backups_root = artifact_root / "backups"
    reports_root = artifact_root / "reports"
    ensure_dir(backups_root)
    ensure_dir(reports_root)

    print(f"[brain_core] mode={mode} scope={args.scope}")
    print(f"[brain_core] artifact_root={artifact_root}")

    activation_log: list[dict[str, Any]] = []

    dump_yaml(reports_root / "resolved_core_publish_manifest.yaml", core_manifest)
    dump_yaml(reports_root / "resolved_infrastructure_publish_routing.yaml", infra_routing)

    dependency_manifest = {
        "core_publish_run": {
            "stamp": stamp,
            "mode": mode,
            "scope": args.scope,
            "modules": [
                {
                    "module_id": module.module_id,
                    "kind": module.kind,
                    "group": module.group,
                    "version": read_version(module.metadata.get("version_file"), module.metadata.get("version_key")),
                    "source_roots": module.source_roots,
                    "target_roots": module.target_roots,
                    "dependencies": module.metadata.get("dependencies", []),
                }
                for module in selected_modules
            ],
            "infrastructure_routes": [
                {
                    "service_id": route["service_id"],
                    "phase": route.get("phase"),
                    "core_member": route.get("core_member", False),
                    "role_hints": route.get("role_hints", []),
                    "implementation_status": route.get("implementation_status", "active"),
                    "publish_driver": route.get("publish_driver"),
                    "publish_targets": route.get("publish_targets", []),
                    "version": read_version(route.get("version_file"), route.get("version_key")),
                    "project_root": route["project_root"],
                    "infra_service_root": route["infra_service_root"],
                    "register_targets": route.get("register_targets", {}),
                    "dependencies": route.get("dependencies", []),
                }
                for route in selected_routes
            ],
        }
    }
    dump_yaml(reports_root / core_manifest["dependency_manifest_name"], dependency_manifest)

    for module in selected_modules:
        execute_module(module, mode, backups_root, activation_log)
    for route in selected_routes:
        execute_infra_route(route, mode, args.allow_manual_gaps, activation_log)

    verification_results: list[dict[str, Any]] = []
    for module in selected_modules:
        if module.kind == "verify_only":
            for required_path in module.metadata.get("required_paths", []):
                verification_results.append(verify_path(required_path))
            if module.module_id == "brain_agents_runtime_assets":
                verification_results.extend(verify_agent_assets(Path("/xkagent_infra/brain/agents")))
        else:
            for target in module.target_roots:
                verification_results.append(verify_path(target))
    for route in selected_routes:
        verification_results.extend(verify_infra_route(route))

    dump_yaml(reports_root / core_manifest["activation_report_name"], {"activation": activation_log})
    dump_yaml(reports_root / core_manifest["verification_report_name"], {"verification": verification_results})
    write_change_summary(reports_root / core_manifest["change_summary_name"], selected_modules, selected_routes)

    missing = [entry for entry in verification_results if entry["status"] != "ok"]
    if missing:
        print("[brain_core] verification warnings:")
        for entry in missing:
            print(f"[brain_core]  - {entry}")
    print("[brain_core] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
