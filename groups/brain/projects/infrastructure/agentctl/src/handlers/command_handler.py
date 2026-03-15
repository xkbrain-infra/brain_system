#!/usr/bin/env python3
"""Command Handler - 内置管理命令处理

处理 Manager 内置命令：/status /agents /route /restart /reload
"""

import importlib.util as _ilu
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.loader import DEFAULT_CONFIG_DIR, YAMLConfigLoader

# SSOT: /xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py
_spec = _ilu.spec_from_file_location("ipc_daemon_client", "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_DaemonClient = _mod.DaemonClient

CONFIG_BASE = DEFAULT_CONFIG_DIR


@dataclass
class CommandResult:
    """命令执行结果"""
    content: str
    restricted_used: bool = False
    success: bool = True
    error: str | None = None


class CommandHandler:
    """内置命令处理器"""

    def __init__(
        self,
        whitelist_path: Path | None = None,
        routing_table_path: Path | None = None,
        audit_logger=None,
        supervisor=None,
        config_loader=None,
        self_agent_name: str = "manager",
    ):
        self.whitelist_path = whitelist_path or CONFIG_BASE / "whitelist.yaml"
        self.routing_table_path = routing_table_path or CONFIG_BASE / "routing_table.yaml"
        self.audit_logger = audit_logger
        self.supervisor = supervisor
        self.config_loader = config_loader or YAMLConfigLoader(config_dir=CONFIG_BASE)
        self.self_agent_name = self_agent_name
        self._whitelist_cache: dict | None = None
        self._whitelist_mtime: float = 0
        self._status_cache: dict | None = None
        self._status_cache_time: float = 0
        self._status_cache_ttl: float = 5.0  # 缓存 5 秒
        self._ipc = _DaemonClient()

    def _log_event(self, event_type: str, payload: dict, user_id: str = None) -> None:
        """记录审计日志"""
        if self.audit_logger:
            self.audit_logger.log_event(event_type, payload, user_id=user_id)

    def _load_whitelist(self) -> dict:
        """加载白名单配置（带缓存）"""
        try:
            config = self.config_loader.get_whitelist()
            return config.get("whitelist", {}) if isinstance(config, dict) else {}
        except Exception:
            return {"admin_users": [], "command_permissions": {"public": [], "restricted": []}}

    def _is_authorized(self, user_id: str, command: str) -> bool:
        """检查用户是否有权限执行命令"""
        whitelist = self._load_whitelist()

        # 检查是否是公开命令
        public_commands = whitelist.get("command_permissions", {}).get("public", [])
        if command in public_commands or any(command.startswith(c) for c in public_commands):
            return True

        # 检查用户是否在白名单
        admin_users = whitelist.get("admin_users", [])
        for admin in admin_users:
            if admin.get("user_id") == user_id:
                permissions = admin.get("permissions", [])
                if command in permissions or any(command.startswith(p) for p in permissions):
                    return True

        return False

    def _get_daemon_response(self, action: str, data: dict) -> dict | None:
        """向 daemon 发送请求"""
        try:
            return self._ipc._send_request(action, data)
        except Exception:
            return None

    def handle(self, command: str, args: list[str], user_ctx: dict) -> CommandResult:
        """处理命令"""
        user_id = user_ctx.get("user_id", "")
        full_command = f"{command} {' '.join(args)}".strip() if args else command

        # 记录命令执行
        self._log_event("command_received", {
            "command": command,
            "args": args,
            "user_id": user_id,
        }, user_id=user_id)

        # 路由到具体处理器
        handlers = {
            "/status": self._handle_status,
            "/agents": self._handle_agents,
            "/context": self._handle_context,
            "/route": self._handle_route,
            "/restart": self._handle_restart,
            "/reload": self._handle_reload,
        }

        handler = handlers.get(command)
        if not handler:
            return CommandResult(
                content=f"未知命令: {command}",
                success=False,
                error="unknown_command",
            )

        # 检查权限
        restricted_commands = ["/restart", "/reload", "/route dump"]
        is_restricted = any(full_command.startswith(rc) for rc in restricted_commands)

        if is_restricted and not self._is_authorized(user_id, full_command):
            self._log_event("command_unauthorized", {
                "command": command,
                "args": args,
                "user_id": user_id,
            }, user_id=user_id)

            whitelist = self._load_whitelist()
            msg = whitelist.get("unauthorized_response", "抱歉，您没有权限执行此命令。")
            return CommandResult(
                content=msg,
                restricted_used=True,
                success=False,
                error="unauthorized",
            )

        # 执行命令
        try:
            result = handler(args, user_ctx)
            result.restricted_used = is_restricted

            self._log_event("command_executed", {
                "command": command,
                "args": args,
                "user_id": user_id,
                "success": result.success,
            }, user_id=user_id)

            return result
        except Exception as e:
            self._log_event("command_error", {
                "command": command,
                "args": args,
                "user_id": user_id,
                "error": str(e),
            }, user_id=user_id)

            return CommandResult(
                content=f"命令执行失败: {e}",
                success=False,
                error=str(e),
            )

    def _handle_status(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /status 命令"""
        now = time.time()

        # 使用缓存（<2s 响应策略）
        if self._status_cache and (now - self._status_cache_time) < self._status_cache_ttl:
            cache_age = int(now - self._status_cache_time)
            return CommandResult(
                content=self._format_status(self._status_cache, cache_age),
                success=True,
            )

        # 获取实时状态
        response = self._get_daemon_response("agent_list", {"include_offline": False})

        if not response or response.get("status") != "ok":
            if self._status_cache:
                cache_age = int(now - self._status_cache_time)
                return CommandResult(
                    content=self._format_status(self._status_cache, cache_age, stale=True),
                    success=True,
                )
            return CommandResult(
                content="无法获取系统状态",
                success=False,
                error="daemon_unavailable",
            )

        # 更新缓存
        self._status_cache = response
        self._status_cache_time = now

        return CommandResult(
            content=self._format_status(response, 0),
            success=True,
        )

    def _format_status(self, data: dict, cache_age: int, stale: bool = False) -> str:
        """格式化状态输出"""
        instances = data.get("instances", []) or []
        online_instances = [i for i in instances if isinstance(i, dict) and i.get("online")]
        online_instance_count = len(online_instances)
        online_agent_count = len({str(i.get("agent_name") or "") for i in online_instances if i.get("agent_name")})

        lines = [
            "📊 **系统状态**",
            f"- 在线实例: {online_instance_count}",
            f"- 在线 Agent(去重): {online_agent_count}",
            f"- 数据时间: {cache_age}s 前{'（陈旧）' if stale else ''}",
        ]

        # 队列状态（如果有）
        stats = data.get("stats", {})
        if stats:
            msgqueue = stats.get("msgqueue", {})
            if msgqueue:
                lines.append(f"- 队列消息: {msgqueue.get('total_messages', 0)}")

        return "\n".join(lines)

    def _handle_agents(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /agents 命令"""
        response = self._get_daemon_response("agent_list", {"include_offline": True})

        if not response or response.get("status") != "ok":
            return CommandResult(
                content="无法获取 Agent 列表",
                success=False,
                error="daemon_unavailable",
            )

        agents = response.get("agents", [])
        if not agents:
            return CommandResult(content="当前没有注册的 Agent", success=True)

        lines = ["🤖 **Agent 列表**", ""]
        for agent in agents:
            name = agent.get("name", "unknown")
            online = "🟢" if agent.get("online") else "🔴"
            idle = agent.get("idle_seconds", 0)

            if idle < 60:
                idle_str = f"{idle}s"
            elif idle < 3600:
                idle_str = f"{idle // 60}m"
            else:
                idle_str = f"{idle // 3600}h"

            lines.append(f"{online} **{name}** (idle: {idle_str})")

        return CommandResult(content="\n".join(lines), success=True)

    # -- /context --------------------------------------------------------

    _TMUX_API = "/xkagent_infra/brain/infrastructure/service/utils/tmux/releases/current/bin/brain_tmux_api"

    @staticmethod
    def _parse_context_usage(text: str) -> float | None:
        """从 tmux pane 文本中解析 context 剩余百分比。

        支持格式:
          - Claude Code: "95% context left"  → 95.0
          - Codex:       "Context: 40.0% used" → 60.0
        """
        # Claude Code: "XX% context left"
        m = re.search(r"(\d+(?:\.\d+)?)%\s*context\s*left", text)
        if m:
            return float(m.group(1))

        # Codex: "Context: XX% used"  (may wrap across lines)
        m = re.search(r"Context:\s*(\d+(?:\.\d+)?)%\s*used", text, re.DOTALL)
        if m:
            return round(100.0 - float(m.group(1)), 1)

        return None

    def _capture_pane(self, tmux_session: str, lines: int = 10) -> str:
        """调用 brain_tmux_api capture-pane 获取文本"""
        try:
            result = subprocess.run(
                [self._TMUX_API, "capture-pane", "-t", tmux_session, "-n", str(lines)],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout or ""
        except Exception:
            return ""

    def _handle_context(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /context 命令 — 显示各 Agent 的 context 剩余"""
        response = self._get_daemon_response("agent_list", {"include_offline": False})
        if not response or response.get("status") != "ok":
            return CommandResult(content="无法获取 Agent 列表", success=False, error="daemon_unavailable")

        instances = response.get("instances", []) or []
        # 只关注有 tmux_session 的 agent 实例
        agents_with_tmux = [
            i for i in instances
            if isinstance(i, dict) and i.get("online") and i.get("tmux_session")
        ]

        if not agents_with_tmux:
            return CommandResult(content="当前没有运行中的 Agent (tmux)", success=True)

        # 按 group 分组: agent_<group>_<role>
        groups: dict[str, list[tuple[str, float | None]]] = {}
        for inst in sorted(agents_with_tmux, key=lambda i: i.get("agent_name", "")):
            name = inst["agent_name"]
            session = inst["tmux_session"]
            pane_text = self._capture_pane(session)
            remaining = self._parse_context_usage(pane_text)

            # 推断 group: agent_<group>_<role>
            parts = name.split("_", 2)  # ["agent", "<group>", "<role>"]
            group = parts[1] if len(parts) >= 3 else "other"
            groups.setdefault(group, []).append((name, remaining))

        lines = ["📊 **Agent Context 状态**", ""]
        for group, members in groups.items():
            lines.append(f"**{group}:**")
            max_name_len = max(len(n) for n, _ in members)
            for name, remaining in members:
                padded = name.ljust(max_name_len)
                if remaining is not None:
                    pct = f"{remaining:g}%"
                    lines.append(f"  🟢 `{padded}` | Context 剩余: {pct}")
                else:
                    lines.append(f"  🟡 `{padded}` | Context: N/A")
            lines.append("")

        return CommandResult(content="\n".join(lines), success=True)

    # -- /route ----------------------------------------------------------

    def _handle_route(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /route 命令"""
        if not args:
            # 显示路由表摘要
            return self._route_show()
        elif args[0] == "test" and len(args) > 1:
            # 测试路由
            message = " ".join(args[1:])
            return self._route_test(message)
        elif args[0] == "dump":
            # 导出完整路由表（受限）
            return self._route_dump()
        else:
            return CommandResult(
                content="用法: /route [test <message>] [dump]",
                success=False,
            )

    def _route_show(self) -> CommandResult:
        """显示路由表摘要"""
        try:
            config = self.config_loader.get_routing_table()
            rt = config.get("routing_table", {}) if isinstance(config, dict) else {}
            defaults = rt.get("defaults", {})
            commands = rt.get("commands", [])
            keyword_rules = rt.get("keyword_rules", [])

            lines = [
                "🔀 **路由表摘要**",
                f"- 默认 Agent: {defaults.get('default_agent', 'N/A')}",
                f"- 无匹配行为: {defaults.get('no_match_behavior', 'N/A')}",
                f"- 命令数量: {len(commands)}",
                f"- 关键词规则: {len(keyword_rules)}",
            ]

            return CommandResult(content="\n".join(lines), success=True)
        except Exception as e:
            return CommandResult(content=f"读取路由表失败: {e}", success=False, error=str(e))

    def _route_test(self, message: str) -> CommandResult:
        """测试路由（不执行）"""
        # 简化版测试 - 实际应调用 router.route()
        try:
            config = self.config_loader.get_routing_table()
            rt = config.get("routing_table", {}) if isinstance(config, dict) else {}
            defaults = rt.get("defaults", {})
            keyword_rules = rt.get("keyword_rules", [])

            # 简单关键词匹配
            matched_rule = None
            target = defaults.get("default_agent", "codex")

            for rule in sorted(keyword_rules, key=lambda r: -r.get("priority", 0) if isinstance(r, dict) else 0):
                if not isinstance(rule, dict):
                    continue
                match = rule.get("match", {})
                pattern = match.get("pattern", "")
                if pattern and pattern in message:
                    matched_rule = pattern
                    target = rule.get("target_agent", target)
                    break

            lines = [
                "🧪 **路由测试**",
                f"- 输入: {message[:50]}{'...' if len(message) > 50 else ''}",
                f"- 目标: {target}",
                f"- 匹配规则: {matched_rule or '默认'}",
            ]

            return CommandResult(content="\n".join(lines), success=True)
        except Exception as e:
            return CommandResult(content=f"路由测试失败: {e}", success=False, error=str(e))

    def _route_dump(self) -> CommandResult:
        """导出完整路由表（受限命令）"""
        try:
            if not self.routing_table_path.exists():
                return CommandResult(content="路由表未配置", success=False)

            with open(self.routing_table_path) as f:
                content = f.read()

            # 截断过长内容
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"

            return CommandResult(
                content=f"```yaml\n{content}\n```",
                success=True,
            )
        except Exception as e:
            return CommandResult(content=f"导出失败: {e}", success=False, error=str(e))

    def _handle_restart(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /restart 命令"""
        if not args:
            return CommandResult(
                content="用法: /restart <agent_name>",
                success=False,
            )

        agent_name = args[0]

        # Prefer IPC control channel to service-agentctl
        resp = self._get_daemon_response(
            "ipc_send",
            {
                "from": self.self_agent_name,
                "to": "service-agentctl",
                "payload": {
                    "cmd": "restart",
                    "agent": agent_name,
                    "reason": "manual_restart",
                    "requested_by": str(user_ctx.get("user_id") or ""),
                },
                "message_type": "request",
            },
        )
        if resp and resp.get("status") == "ok":
            return CommandResult(
                content=f"✅ 已通知 launcher 重启 `{agent_name}` (msg_id={resp.get('msg_id')})",
                success=True,
            )

        # Fallback to local supervisor if available
        if self.supervisor:
            result = self.supervisor.restart(agent_name, reason="manual_restart")
            if result.success:
                return CommandResult(
                    content=f"✅ Agent `{agent_name}` 重启命令已发送 (attempt #{result.attempt})",
                    success=True,
                )
            return CommandResult(
                content=f"❌ Agent `{agent_name}` 重启失败: {result.error}",
                success=False,
                error=result.error,
            )

        return CommandResult(content="❌ launcher 不可用", success=False, error="launcher_unavailable")

    def _handle_reload(self, args: list[str], user_ctx: dict) -> CommandResult:
        """处理 /reload 命令"""
        # Notify launcher to reload its config as well
        self._get_daemon_response(
            "ipc_send",
            {
                "from": self.self_agent_name,
                "to": "service-agentctl",
                "payload": {"cmd": "reload_config", "reason": "manual_reload"},
                "message_type": "request",
            },
        )

        try:
            self.config_loader.reload()
            # 清除本地缓存
            self._whitelist_cache = None
            self._status_cache = None
            return CommandResult(content="✅ 配置已重载", success=True)
        except Exception as e:
            return CommandResult(content=f"❌ 配置重载失败: {e}", success=False, error=str(e))
