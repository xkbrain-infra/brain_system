#!/usr/bin/env bash
#
# init-secrets.sh - Docker 容器首次启动时自动初始化 Secrets
#
# 职责：
#   1. 创建 secrets 目录结构
#   2. 生成 SSH host keys（如果不存在）
#   3. 生成 SSH client key pair 用于登录（如果不存在 authorized_keys）
#   4. 输出 key 信息到日志
#
# 环境变量（从 global.env.yaml / .env 读取）：
#   DEPLOYMENT_NAME       - 部署名称 (默认: xk-agent-infra)
#   INSTANCE_ID           - 实例ID (默认: "")
#   ENVIRONMENT           - 环境: development|staging|production
#   SSH_PORT              - SSH 映射端口 (默认: 8622)
#   CONTAINER_PREFIX      - 容器名前缀 (默认: XKAgentInfra)
#   IPC_AGENT_PREFIX      - IPC Agent 前缀 (默认: agent-brain)
#   DEFAULT_PASSWORD      - 默认密码 (默认: aigroup)
#   DEFAULT_USER          - 默认用户 (默认: root)
#   SSH_HOST_KEY_TYPES    - Host key 类型 (默认: "rsa ecdsa ed25519")
#   SSH_CLIENT_KEY_TYPE   - Client key 类型 (默认: ed25519)
#   SSH_CLIENT_KEY_NAME   - Client key 文件名 (默认: id_ed25519)
#   KEY_COMMENT_FORMAT    - Key 注释格式 (默认: xkagent-{hostname}-{date})
#   VERBOSE               - 详细日志 (默认: true)
#

set -euo pipefail

SCRIPT_NAME="init-secrets"

# ============================================
# 配置加载（带默认值，向后兼容）
# ============================================

DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-xk-agent-infra}"
INSTANCE_ID="${INSTANCE_ID:-}"
ENVIRONMENT="${ENVIRONMENT:-development}"
SSH_PORT="${SSH_PORT:-8622}"
CONTAINER_PREFIX="${CONTAINER_PREFIX:-XKAgentInfra}"
IPC_AGENT_PREFIX="${IPC_AGENT_PREFIX:-agent-brain}"
DEFAULT_PASSWORD="${DEFAULT_PASSWORD:-aigroup}"
DEFAULT_USER="${DEFAULT_USER:-root}"
SSH_HOST_KEY_TYPES="${SSH_HOST_KEY_TYPES:-rsa ecdsa ed25519}"
SSH_CLIENT_KEY_TYPE="${SSH_CLIENT_KEY_TYPE:-ed25519}"
SSH_CLIENT_KEY_NAME="${SSH_CLIENT_KEY_NAME:-id_${SSH_CLIENT_KEY_TYPE}}"
KEY_COMMENT_FORMAT="${KEY_COMMENT_FORMAT:-xkagent-{hostname}-{date}}"
VERBOSE="${VERBOSE:-true}"

# 路径配置（从 global.env.yaml 同步）
BRAIN_ROOT="${BRAIN_PATH:-/xkagent_infra/brain}"
SECRETS_ROOT="${SECRETS_ROOT:-${BRAIN_ROOT}/secrets/system}"
SSH_SECRETS_DIR="${SSH_SECRETS_DIR:-${SECRETS_ROOT}/ssh}"
HOST_KEYS_DIR="${HOST_KEYS_DIR:-${SSH_SECRETS_DIR}/host_keys}"
AGENT_AUTH_ROOT="${AGENT_AUTH_ROOT:-${SECRETS_ROOT}/agents/auth}"
SSH_DIR="${SSH_DIR:-/root/.ssh}"
AUTH_KEYS="${AUTH_KEYS:-${SSH_DIR}/authorized_keys}"

# 计算实际使用的容器名
if [[ -n "$INSTANCE_ID" ]]; then
    CONTAINER_NAME="${CONTAINER_PREFIX}-${INSTANCE_ID}"
else
    CONTAINER_NAME="${CONTAINER_PREFIX}"
fi

# ============================================
# 日志函数
# ============================================

log() {
    if [[ "$VERBOSE" == "true" ]]; then
        printf "[%s] %s\n" "$SCRIPT_NAME" "$*"
    fi
}

log_warn() {
    printf "[%s][WARN] %s\n" "$SCRIPT_NAME" "$*" >&2
}

log_info() {
    printf "[%s][INFO] %s\n" "$SCRIPT_NAME" "$*"
}

# ============================================
# 核心功能
# ============================================

# 创建目录结构
ensure_dirs() {
    log "ensuring directory structure..."
    log "  secrets root: $SECRETS_ROOT"
    log "  host keys:    $HOST_KEYS_DIR"
    log "  agent auth:   $AGENT_AUTH_ROOT"
    log "  ssh dir:      $SSH_DIR"

    mkdir -p "$HOST_KEYS_DIR"
    mkdir -p "$AGENT_AUTH_ROOT"
    mkdir -p "$SSH_DIR"

    chmod 700 "$SSH_SECRETS_DIR" 2>/dev/null || true
    chmod 700 "$HOST_KEYS_DIR"
    chmod 700 "$AGENT_AUTH_ROOT"
    chmod 700 "$SSH_DIR"

    log "directory structure ready"
}

# 生成 SSH host keys（如果不存在）
init_host_keys() {
    log "initializing SSH host keys..."
    log "  key types: $SSH_HOST_KEY_TYPES"

    local generated=0

    for key_type in $SSH_HOST_KEY_TYPES; do
        local key_file="ssh_host_${key_type}_key"
        local host_key_path="${HOST_KEYS_DIR}/${key_file}"

        if [[ -f "$host_key_path" ]]; then
            log_info "found existing host key: $key_type"
            cp -f "$host_key_path" "/etc/ssh/${key_file}"
            chmod 600 "/etc/ssh/${key_file}"
            if [[ -f "${host_key_path}.pub" ]]; then
                cp -f "${host_key_path}.pub" "/etc/ssh/${key_file}.pub"
                chmod 644 "/etc/ssh/${key_file}.pub"
            fi
        else
            log_info "generating new host key: $key_type"
            ssh-keygen -t "$key_type" -f "/etc/ssh/${key_file}" -N "" -C "$(hostname)" 2>/dev/null || {
                log_warn "failed to generate $key_type key, skipping"
                continue
            }
            cp -f "/etc/ssh/${key_file}" "$host_key_path"
            cp -f "/etc/ssh/${key_file}.pub" "${host_key_path}.pub"
            chmod 600 "$host_key_path"
            chmod 644 "${host_key_path}.pub"
            generated=$((generated + 1))
        fi
    done

    if [[ $generated -gt 0 ]]; then
        log "generated $generated new host key(s)"
    else
        log "all host keys exist, using persistent keys"
    fi
}

# 生成 key 注释
generate_key_comment() {
    local hostname
    local date_str
    hostname=$(hostname)
    date_str=$(date +%Y%m%d)
    echo "${KEY_COMMENT_FORMAT//\{hostname\}/$hostname}"
    echo "${KEY_COMMENT_FORMAT//\{date\}/$date_str}"
    echo "${KEY_COMMENT_FORMAT//\{deployment_name\}/$DEPLOYMENT_NAME}"
}

# 生成客户端 SSH key pair 用于登录
init_client_keys() {
    log "initializing client SSH keys..."
    log "  key type: $SSH_CLIENT_KEY_TYPE"
    log "  key name: $SSH_CLIENT_KEY_NAME"

    # 如果已经有 authorized_keys，保留它
    if [[ -s "$AUTH_KEYS" ]]; then
        log_info "existing authorized_keys found, preserving"
        # 同步到 secrets 目录作为备份
        cp -f "$AUTH_KEYS" "${SSH_SECRETS_DIR}/authorized_keys.backup"
        return 0
    fi

    # 检查 secrets 目录是否已有 key
    if [[ -f "${SSH_SECRETS_DIR}/${SSH_CLIENT_KEY_NAME}.pub" ]]; then
        log_info "found existing client key in secrets"
        cat "${SSH_SECRETS_DIR}/${SSH_CLIENT_KEY_NAME}.pub" > "$AUTH_KEYS"
        chmod 600 "$AUTH_KEYS"
        log_info "restored authorized_keys from secrets"
        return 0
    fi

    # 生成新的 key pair
    log_info "generating new SSH key pair for container access..."

    local key_name="$SSH_CLIENT_KEY_NAME"
    local private_key="${SSH_SECRETS_DIR}/${key_name}"
    local public_key="${private_key}.pub"
    local comment
    comment=$(generate_key_comment)

    ssh-keygen -t "$SSH_CLIENT_KEY_TYPE" -f "$private_key" -N "" -C "$comment" 2>/dev/null || {
        log_warn "failed to generate client key"
        return 1
    }
    chmod 600 "$private_key"
    chmod 644 "$public_key"

    # 添加到 authorized_keys
    cat "$public_key" > "$AUTH_KEYS"
    chmod 600 "$AUTH_KEYS"

    log "==================================================="
    log "NEW SSH KEY PAIR GENERATED"
    log "==================================================="
    log "Deployment:    $DEPLOYMENT_NAME"
    [[ -n "$INSTANCE_ID" ]] && log "Instance ID:   $INSTANCE_ID"
    log "Container:     $CONTAINER_NAME"
    log "Environment:   $ENVIRONMENT"
    log ""
    log "Private key:   $private_key"
    log "Public key:    $public_key"
    log ""
    log "To connect to this container, use:"
    log "  ssh -p $SSH_PORT -i $private_key ${DEFAULT_USER}@<HOST>"
    log ""
    log "Or copy the private key to your local machine:"
    log "  docker cp ${CONTAINER_NAME}:${private_key} ./xkagent-key"
    log "  ssh -p $SSH_PORT -i ./xkagent-key ${DEFAULT_USER}@<HOST>"
    log "==================================================="
}

# 显示连接信息
show_connection_info() {
    log "==================================================="
    log "CONTAINER SSH ACCESS INFORMATION"
    log "==================================================="
    log "Deployment:    $DEPLOYMENT_NAME"
    [[ -n "$INSTANCE_ID" ]] && log "Instance ID:   $INSTANCE_ID"
    log "Container:     $CONTAINER_NAME"
    log "Environment:   $ENVIRONMENT"
    log "IPC Prefix:    $IPC_AGENT_PREFIX"
    log ""
    log "SSH Port:      $SSH_PORT (host mapped port)"
    log "User:          $DEFAULT_USER"
    log "Password:      $DEFAULT_PASSWORD (default, SSH key recommended)"
    log ""
    log "SSH Host Keys (fingerprints):"
    for pub_key in /etc/ssh/ssh_host_*.pub; do
        if [[ -f "$pub_key" ]]; then
            local key_type
            key_type=$(basename "$pub_key" .pub | sed 's/ssh_host_//' | sed 's/_key//')
            local fingerprint
            fingerprint=$(ssh-keygen -lf "$pub_key" 2>/dev/null | awk '{print $2}')
            log "  $key_type: $fingerprint"
        fi
    done
    log "==================================================="
}

# 显示配置摘要（调试用）
show_config_summary() {
    log "configuration loaded:"
    log "  DEPLOYMENT_NAME=$DEPLOYMENT_NAME"
    log "  INSTANCE_ID=$INSTANCE_ID"
    log "  ENVIRONMENT=$ENVIRONMENT"
    log "  SSH_PORT=$SSH_PORT"
    log "  CONTAINER_PREFIX=$CONTAINER_PREFIX"
    log "  IPC_AGENT_PREFIX=$IPC_AGENT_PREFIX"
}

# ============================================
# 主流程
# ============================================

main() {
    log "starting secrets initialization..."
    show_config_summary

    ensure_dirs
    init_host_keys
    init_client_keys
    show_connection_info

    log "secrets initialization completed"
}

main "$@"
