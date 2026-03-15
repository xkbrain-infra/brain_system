#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "$PROJECT_ROOT" == "/xkagent_infra/brain/base" ]]; then
  PROJECT_ROOT="/xkagent_infra/groups/brain/projects/base"
fi
RELEASES_ROOT="$PROJECT_ROOT/releases/publish_backups"
TARGET_ROOT="/xkagent_infra/brain/base"
AGENTCTL_CONFIG="/xkagent_infra/brain/infrastructure/config/agentctl"

ROOT_FILES=("index.yaml" "INIT.md.new" "README.md" "PUBLISH_MANIFEST.yaml")
DOMAINS=("evolution" "hooks" "knowledge" "mcp" "scripts" "skill" "spec" "workflow")

MODE="dry-run"
DOMAIN="all"

usage() {
  cat <<'EOF'
Usage:
  publish_base.sh --dry-run [--domain evolution|hooks|knowledge|mcp|scripts|skill|spec|workflow|root|agents|all]
  publish_base.sh --publish [--domain evolution|hooks|knowledge|mcp|scripts|skill|spec|workflow|root|agents|all]

Domains:
  root     Publish root files (index.yaml, INIT.md.new, README.md, PUBLISH_MANIFEST.yaml)
  mcp      Publish mcp/ to brain/base and refresh /brain/bin/mcp runtime entrypoints
  scripts  Publish scripts/ to brain/base/scripts
  skill    Publish skill/ from projects/base to brain/base
  agents   Deploy skills to each agent .claude/skills/ per skill_bindings.yaml
  all      Run all domains including agents

Behavior:
  --dry-run  Print actions only.
  --publish  Backup existing targets, then publish.
EOF
}

log() {
  printf '[brain_base] %s\n' "$*"
}

fail() {
  printf '[brain_base] ERROR: %s\n' "$*" >&2
  exit 1
}

require_dir() {
  local path="$1"
  [[ -d "$path" ]] || fail "missing directory: $path"
}

run_cmd() {
  if [[ "$MODE" == "dry-run" ]]; then
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

backup_target() {
  local target="$1"
  local backup_root="$2"

  [[ -e "$target" ]] || return 0

  if [[ "$MODE" == "dry-run" ]]; then
    log "would backup $target -> $backup_root"
    return 0
  fi

  mkdir -p "$backup_root"
  cp -a "$target" "$backup_root/"
}

mirror_dir() {
  local src="$1"
  local dst="$2"
  local backup_root="$3"

  require_dir "$src"
  backup_target "$dst" "$backup_root"

  run_cmd mkdir -p "$dst"
  if [[ -d "$dst" ]]; then
    run_cmd find "$dst" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
  run_cmd cp -a "$src"/. "$dst"/
}

publish_root_file() {
  local name="$1"
  local src="$PROJECT_ROOT/$name"
  local dst="$TARGET_ROOT/$name"
  local backup_root="$RELEASES_ROOT/$STAMP/root"

  [[ -f "$src" ]] || fail "missing root file: $src"
  backup_target "$dst" "$backup_root"
  run_cmd mkdir -p "$(dirname "$dst")"
  run_cmd cp -f "$src" "$dst"
}

publish_domain() {
  local name="$1"
  local src="$PROJECT_ROOT/$name"
  local dst="$TARGET_ROOT/$name"
  local backup_root="$RELEASES_ROOT/$STAMP/$name"

  log "publishing domain: $src -> $dst"
  mirror_dir "$src" "$dst" "$backup_root"
}

publish_root() {
  local name
  for name in "${ROOT_FILES[@]}"; do
    log "publishing root file: $PROJECT_ROOT/$name -> $TARGET_ROOT/$name"
    publish_root_file "$name"
  done
}

sync_mcp_runtime() {
  log "syncing MCP runtime entrypoints via build_bin.sh install mcp (mode=$MODE)"
  run_cmd bash "$PROJECT_ROOT/scripts/build_bin.sh" install mcp
}

build_mcp_artifacts() {
  log "building MCP artifacts before publish (mode=$MODE)"
  run_cmd bash "$PROJECT_ROOT/scripts/build_bin.sh" build mcp
}

deploy_agents() {
  local skill_source="$TARGET_ROOT/skill"
  local bindings="$AGENTCTL_CONFIG/skill_bindings.yaml"
  local registry="$AGENTCTL_CONFIG/agents_registry.yaml"
  local dry_run="$MODE"

  log "deploying skills to agents (mode=$dry_run)"

  require_dir "$skill_source"
  [[ -f "$bindings" ]] || fail "missing skill_bindings.yaml: $bindings"
  [[ -f "$registry" ]] || fail "missing agents_registry.yaml: $registry"

  python3 - "$skill_source" "$bindings" "$registry" "$dry_run" <<'PYEOF'
import sys, os, shutil
from pathlib import Path

skill_source = Path(sys.argv[1])
bindings_file = Path(sys.argv[2])
registry_file = Path(sys.argv[3])
dry_run = sys.argv[4] == "dry-run"

try:
    import yaml
except ImportError:
    # fallback: minimal yaml parser for simple structures
    import re, json

    def load_yaml(path):
        # Use python -c with PyYAML if available, otherwise parse manually
        import subprocess
        result = subprocess.run(
            ["python3", "-c", f"import yaml,json,sys; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))", str(path)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        raise RuntimeError(f"Cannot parse YAML: {path}")
else:
    def load_yaml(path):
        with open(path) as f:
            return yaml.safe_load(f)

bindings_data = load_yaml(bindings_file)
registry_data = load_yaml(registry_file)

bindings = bindings_data["skill_bindings"]
# groups is a top-level key, not nested under agents_registry
groups_data = registry_data.get("groups", {})

role_skills = {role: data.get("default_skills", [])
               for role, data in bindings.get("roles", {}).items()}
agent_extra = {name: data.get("extra_skills", [])
               for name, data in bindings.get("agents", {}).items()}

agents = []
for group_agents in groups_data.values():
    if isinstance(group_agents, list):
        agents.extend(group_agents)

prefix = "DRY-RUN: " if dry_run else ""

for agent in agents:
    name = agent["name"]
    role = agent.get("role", "custom")
    agent_path = Path(agent["path"])
    skills_dir = agent_path / ".claude" / "skills"

    effective = list(role_skills.get(role, []))
    for s in agent_extra.get(name, []):
        if s not in effective:
            effective.append(s)

    if not effective:
        continue

    print(f"[brain_base] {prefix}agent={name} role={role} skills={effective}")

    for skill in effective:
        src = skill_source / skill
        dst = skills_dir / skill

        if not src.is_dir():
            print(f"[brain_base]   WARN: skill source not found: {src}", file=sys.stderr)
            continue

        if dry_run:
            print(f"[brain_base]   would deploy {src} -> {dst}")
        else:
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                shutil.copy2(item, dst / item.name)
            print(f"[brain_base]   deployed {skill} -> {dst}")

    # Remove skills no longer in effective list
    if not dry_run and skills_dir.exists():
        for existing in skills_dir.iterdir():
            if existing.is_dir() and existing.name not in effective:
                shutil.rmtree(existing)
                print(f"[brain_base]   removed stale skill: {existing.name} from {name}")
    elif dry_run and skills_dir.exists():
        for existing in skills_dir.iterdir():
            if existing.is_dir() and existing.name not in effective:
                print(f"[brain_base]   would remove stale skill: {existing.name} from {name}")

PYEOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      ;;
    --publish)
      MODE="publish"
      ;;
    --domain)
      shift
      [[ $# -gt 0 ]] || fail "--domain requires a value"
      DOMAIN="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
  shift
done

case "$DOMAIN" in
  root|evolution|hooks|knowledge|mcp|scripts|skill|spec|workflow|sandbox|agents|all)
    ;;
  *)
    fail "invalid domain: $DOMAIN"
    ;;
esac

STAMP="$(date +%Y%m%d_%H%M%S)"

require_dir "$PROJECT_ROOT"
require_dir "$TARGET_ROOT"

log "mode=$MODE domain=$DOMAIN"
log "project_root=$PROJECT_ROOT"
log "target_root=$TARGET_ROOT"

if [[ "$DOMAIN" == "root" || "$DOMAIN" == "all" ]]; then
  publish_root
fi

for name in "${DOMAINS[@]}"; do
  require_dir "$PROJECT_ROOT/$name"
  if [[ "$DOMAIN" == "$name" || "$DOMAIN" == "all" ]]; then
    if [[ "$name" == "mcp" ]]; then
      build_mcp_artifacts
    fi
    publish_domain "$name"
  fi
done

if [[ "$DOMAIN" == "mcp" || "$DOMAIN" == "all" ]]; then
  sync_mcp_runtime
fi

if [[ "$DOMAIN" == "sandbox" || "$DOMAIN" == "all" ]]; then
  # Sandbox 是特殊域，直接复制到 brain/base/sandbox/
  sandbox_src="$PROJECT_ROOT/sandbox"
  sandbox_dst="$TARGET_ROOT/sandbox"
  if [[ -d "$sandbox_src" ]]; then
    log "publishing domain: $sandbox_src -> $sandbox_dst"
    backup_root="$RELEASES_ROOT/$STAMP/sandbox"
    mirror_dir "$sandbox_src" "$sandbox_dst" "$backup_root"
  fi
fi

if [[ "$DOMAIN" == "agents" || "$DOMAIN" == "all" ]]; then
  deploy_agents
fi

log "done"
