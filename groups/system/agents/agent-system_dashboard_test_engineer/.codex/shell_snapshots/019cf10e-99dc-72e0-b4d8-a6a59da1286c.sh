# Snapshot file
# Unset all aliases to avoid conflicts with functions
# Functions

# setopts 3
set -o braceexpand
set -o hashall
set -o interactive-comments

# aliases 0

# exports 31
declare -x AGENTCTL_CONFIG_DIR="/xkagent_infra/brain/infrastructure/config/agentctl"
declare -x AGENT_MANAGER_CONFIG_DIR="/xkagent_infra/brain/infrastructure/config/agentctl"
declare -x BRAIN_ENABLED_SKILLS="lep"
declare -x BRAIN_IPC_SOCKET="/tmp/brain_ipc.sock"
declare -x BRAIN_PATH="/xkagent_infra/brain"
declare -x BRAIN_ROLE_DEFAULT_SKILLS="lep"
declare -x BRAIN_SKILL_BINDINGS_FILE="/xkagent_infra/brain/infrastructure/config/agentctl/skill_bindings.yaml"
declare -x BRAIN_TRANSPORT_MODE="proxy"
declare -x CODEX_HOME="/xkagent_infra/groups/system/agents/agent-system_dashboard_test_engineer/.codex"
declare -x CODEX_MANAGED_BY_NPM="1"
declare -x DEBIAN_FRONTEND="noninteractive"
declare -x ENVIRONMENT="development"
declare -x HOME="/root"
declare -x HOSTNAME="XKAgentInfra"
declare -x IS_SANDBOX="1"
declare -x LC_CTYPE="C.UTF-8"
declare -x PATH="/xkagent_infra/groups/system/agents/agent-system_dashboard_test_engineer/.codex/tmp/arg0/codex-arg0EB7Fwa:/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/path:/root/.local/bin:/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/xkagent_infra/brain/bin:/xkagent_infra/brain/bin:/brain/bin"
declare -x PYTHONPATH="/xkagent_infra/brain/infrastructure/service/agentctl"
declare -x SHELL="/bin/bash"
declare -x SHLVL="1"
declare -x SUPERVISOR_ENABLED="1"
declare -x SUPERVISOR_GROUP_NAME="agent_orchestrator"
declare -x SUPERVISOR_PROCESS_NAME="agent_orchestrator"
declare -x SUPERVISOR_SERVER_URL="unix:///var/run/supervisor.sock"
declare -x TERM="tmux-256color"
declare -x TERM_PROGRAM="tmux"
declare -x TERM_PROGRAM_VERSION="3.4"
declare -x TMUX="/tmp/tmux-0/default,22341,10"
declare -x TMUX_PANE="%10"
declare -x TMUX_SESSION="agent-system_dashboard_test_engineer"
declare -x TZ="Asia/Shanghai"
