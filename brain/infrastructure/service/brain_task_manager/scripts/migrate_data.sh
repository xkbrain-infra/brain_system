#!/usr/bin/env bash
# migrate_data.sh - 将旧 task_manager 数据迁移到 brain_task_manager
# 用法: ./migrate_data.sh [--dry-run] [--force]
# BS-026

set -euo pipefail

# ── 配置 ──────────────────────────────────────────────────────────────────────
SRC_DIR="/brain/infrastructure/service/task_manager/data"
DST_DIR="/brain/infrastructure/service/brain_task_manager/data"
BACKUP_DIR="/brain/runtime/backup/brain_task_manager_migrate_$(date +%Y%m%d_%H%M%S)"
LOG_FILE="/brain/runtime/logs/brain_task_manager_migrate.log"

DRY_RUN=false
FORCE=false

# ── 参数解析 ──────────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --force)   FORCE=true ;;
    *)
      echo "未知参数: $arg" >&2
      echo "用法: $0 [--dry-run] [--force]" >&2
      exit 1
      ;;
  esac
done

# ── 日志函数 ──────────────────────────────────────────────────────────────────
log() {
  local level="$1"; shift
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
  echo "$msg"
  echo "$msg" >> "$LOG_FILE"
}

# ── 验证 JSON 可读性 ───────────────────────────────────────────────────────────
validate_json() {
  local file="$1"
  if ! python3 -c "import json, sys; json.load(open('$file'))" 2>/dev/null; then
    log "ERROR" "JSON 格式无效: $file"
    return 1
  fi
  log "INFO" "JSON 验证通过: $file"
  return 0
}

# ── 主流程 ────────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
log "INFO" "=== brain_task_manager 数据迁移开始 ==="
log "INFO" "模式: $([ "$DRY_RUN" = true ] && echo 'DRY-RUN（只验证，不写入）' || echo '实际迁移')"
log "INFO" "源目录: $SRC_DIR"
log "INFO" "目标目录: $DST_DIR"

# 1. 验证源文件存在且可读
FILES_TO_MIGRATE=("tasks.json" "specs.json")
VALIDATION_FAILED=false

for fname in "${FILES_TO_MIGRATE[@]}"; do
  src_file="$SRC_DIR/$fname"
  if [ ! -f "$src_file" ]; then
    log "ERROR" "源文件不存在: $src_file"
    VALIDATION_FAILED=true
    continue
  fi
  if [ ! -r "$src_file" ]; then
    log "ERROR" "源文件不可读: $src_file"
    VALIDATION_FAILED=true
    continue
  fi
  if ! validate_json "$src_file"; then
    VALIDATION_FAILED=true
    continue
  fi
  log "INFO" "  大小: $(wc -c < "$src_file") bytes，条目数: $(python3 -c "import json; d=json.load(open('$src_file')); print(len(d) if isinstance(d, list) else len(d.get('tasks', d.get('specs', []))))" 2>/dev/null || echo '未知')"
done

if [ "$VALIDATION_FAILED" = true ]; then
  log "ERROR" "验证失败，迁移中止"
  exit 2
fi

log "INFO" "所有源文件验证通过"

if [ "$DRY_RUN" = true ]; then
  log "INFO" "DRY-RUN 完成，无文件写入"
  exit 0
fi

# 2. 检查目标是否已有数据（防覆盖）
for fname in "${FILES_TO_MIGRATE[@]}"; do
  dst_file="$DST_DIR/$fname"
  if [ -f "$dst_file" ] && [ "$FORCE" = false ]; then
    log "ERROR" "目标文件已存在: $dst_file （使用 --force 强制覆盖）"
    exit 3
  fi
done

# 3. 备份目标目录现有数据
if [ -d "$DST_DIR" ] && [ "$(ls -A "$DST_DIR" 2>/dev/null)" ]; then
  log "INFO" "备份目标目录现有数据到: $BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"
  cp -r "$DST_DIR"/. "$BACKUP_DIR/" 2>/dev/null || true
fi

# 4. 执行迁移
mkdir -p "$DST_DIR"
for fname in "${FILES_TO_MIGRATE[@]}"; do
  src_file="$SRC_DIR/$fname"
  dst_file="$DST_DIR/$fname"
  log "INFO" "复制: $src_file → $dst_file"
  cp "$src_file" "$dst_file"
  # 验证目标文件
  if ! validate_json "$dst_file"; then
    log "ERROR" "目标文件验证失败: $dst_file"
    exit 4
  fi
done

log "INFO" "=== 迁移完成 ==="
log "INFO" "迁移文件: ${FILES_TO_MIGRATE[*]}"
log "INFO" "备份位置: $BACKUP_DIR"
