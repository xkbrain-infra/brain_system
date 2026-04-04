#!/bin/bash
# 修复被 volume mount 覆盖的 /xkagent_infra/brain 符号链接
if [ ! -L /xkagent_infra/brain ] && [ -d /xkagent_infra/brain ] && [ -z "$(ls -A /xkagent_infra/brain)" ]; then
    rm -rf /xkagent_infra/brain
    ln -sf /brain /xkagent_infra/brain
fi

# 添加 host.docker.internal 到 /etc/hosts
# 注意: 在 host 网络模式下, 需要使用宿主机的实际 IP 而不是 127.0.0.1
# HOST_IP 环境变量由 docker-compose 传入
if ! grep -q "host.docker.internal" /etc/hosts; then
    # 默认使用宿主机的 bridge 网卡 IP (docker0)
    HOST_DEFAULT=$(ip route | grep default | awk '{print $3}' | head -1)
    HOST_IP_ADDR="${HOST_IP:-${HOST_DEFAULT:-10.200.19.2}}"
    echo "${HOST_IP_ADDR} host.docker.internal" >> /etc/hosts
fi

# 创建运行时目录 (如果不存在)
SANDBOX_RUNTIME="/xkagent_infra/runtime/sandbox/${SANDBOX_INSTANCE_ID:-46v7xs}"
mkdir -p "${SANDBOX_RUNTIME}"
TMUX_RUNTIME_DIR="${SANDBOX_RUNTIME}/.tmux"
mkdir -p "${TMUX_RUNTIME_DIR}"

# 修复 /tmp/tmux-* 权限 (tmux 要求 700)
if [ -d /tmp/tmux-0 ]; then
    chmod 700 /tmp/tmux-0
fi
# 让交互 shell 直接使用当前 sandbox 的 tmux socket 目录。
install_tmux_shell_hook() {
    local rc_file="$1"
    local marker_begin="# >>> XKAGENT_SANDBOX_TMUX >>>"
    local marker_end="# <<< XKAGENT_SANDBOX_TMUX <<<"

    touch "${rc_file}"
    if grep -Fq "${marker_begin}" "${rc_file}"; then
        return 0
    fi

    cat >>"${rc_file}" <<'HOOK'
# >>> XKAGENT_SANDBOX_TMUX >>>
if [ -n "${SANDBOX_INSTANCE_ID:-}" ]; then
    export SANDBOX_RUNTIME="/xkagent_infra/runtime/sandbox/${SANDBOX_INSTANCE_ID}"
    export TMUX_TMPDIR="${SANDBOX_RUNTIME}/.tmux"
fi
# <<< XKAGENT_SANDBOX_TMUX <<<
HOOK
}

install_tmux_shell_hook /root/.bashrc
install_tmux_shell_hook /home/ubuntu/.bashrc

# 以 ubuntu 身份执行命令 (设置 TMUX_TMPDIR 环境变量)
exec su ubuntu -c "export SANDBOX_RUNTIME=${SANDBOX_RUNTIME} && export TMUX_TMPDIR=${TMUX_RUNTIME_DIR} && cd ${SANDBOX_RUNTIME} && bash -lc 'sleep infinity'"
