#!/usr/bin/env python3
"""
seed_task_graph.py — task_graph → task_manager 初始化脚本
==========================================================
在 task_modeling 完成后、进入 execution 前由 orchestrator 调用。
读取 task_graph.yaml，通过 IPC 将所有任务批量写入 task_manager。

用法:
    python3 seed_task_graph.py --task-graph /workspace/project/spec/06_tasks/task_graph.yaml

环境变量:
    BRAIN_IPC_SOCKET   — IPC socket 路径（默认 /tmp/brain_ipc.sock）
    ORCHESTRATOR_ID    — 发送方 agent name（默认 brain_task_manager_seeder）
    PROJECT_ID         — 项目 ID（可覆盖 task_graph 中的值）
    GROUP_ID           — group ID

退出码:
    0 — 全部成功
    1 — 参数错误或文件不存在
    2 — 部分任务创建失败（失败详情写入 stderr）
"""

import argparse
import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ─── 配置 ────────────────────────────────────────────────────────────────────

IPC_SOCKET   = os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock")
SENDER_NAME  = os.environ.get("ORCHESTRATOR_ID", "brain_task_manager_seeder")
PROJECT_ID   = os.environ.get("PROJECT_ID", "")
GROUP_ID     = os.environ.get("GROUP_ID", "")

# task_manager IPC agent name（固定）
TM_AGENT = "brain_task_manager"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seed] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("seed_task_graph")


# ─── 状态映射（见 task_graph_schema.yaml）────────────────────────────────────

# project_delivery 初始状态 → task_manager (status, tags)
# task_graph 中的 task 进入 task_manager 时全部以 BACKLOG 或 READY 写入
def _initial_tm_state(task_id: str, initial_ready_set: list[str]) -> tuple[str, list[str]]:
    """根据 initial_ready_set 决定初始 status（使用正式状态名）"""
    if task_id in initial_ready_set:
        return "ready", []   # 直接写入 Ready 状态，无需 tags 变通
    return "pending", []


# ─── IPC 通信 ─────────────────────────────────────────────────────────────────

class IpcClient:
    """
    轻量 IPC 客户端，直接通过 Unix socket 与 brain_ipc daemon 通信。
    协议：换行符分隔的 JSON，与 C++ IpcClient::DoRequest 对称。
    """

    def __init__(self, socket_path: str, sender: str):
        self.socket_path = socket_path
        self.sender = sender

    def _request(self, payload: dict) -> dict:
        """发送一条请求并等待响应"""
        raw = json.dumps(payload, ensure_ascii=False) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(self.socket_path)
            s.sendall(raw.encode())
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    break
        return json.loads(buf.decode().strip())

    def task_create(self, task: dict) -> dict:
        """
        向 brain_task_manager 发送 task_create 消息。
        对应 MessageRouter::HandleTaskCreate。
        """
        msg = {
            "from":       self.sender,
            "to":         TM_AGENT,
            "event_type": "task_create",
            "payload":    task,
        }
        return self._request(msg)

    def task_query(self, filters: dict | None = None) -> dict:
        """查询任务（用于验证 seeding 结果）"""
        msg = {
            "from":       self.sender,
            "to":         TM_AGENT,
            "event_type": "task_query",
            "payload":    filters or {},
        }
        return self._request(msg)


# ─── Task Graph 加载与转换 ────────────────────────────────────────────────────

def load_task_graph(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_tm_task(task_def: dict, graph: dict) -> dict:
    """
    将 task_graph 中的 TaskDef 转换为 task_manager Task 格式。
    字段对应关系见 task_graph_schema.yaml 和 types.h Task struct。
    """
    task_id = task_def["task_id"]
    initial_ready_set = graph.get("initial_ready_set", [])
    status, state_tags = _initial_tm_state(task_id, initial_ready_set)

    # 合并 schema 中定义的 tags 与状态 tags
    user_tags = task_def.get("tags", [])
    all_tags = list(set(user_tags + state_tags))

    # 在 description 中附加结构化元数据（review_by、kind、stage 等
    # task_manager Task struct 没有这些字段，用 description JSON 尾部编码）
    description = task_def.get("description", "")
    meta = {}
    if task_def.get("review_by"):
        meta["review_by"] = task_def["review_by"]
    if task_def.get("kind"):
        meta["kind"] = task_def["kind"]
    if task_def.get("stage"):
        meta["stage"] = task_def["stage"]
    if meta:
        description = description.rstrip()
        description += f"\n\n__meta__: {json.dumps(meta, ensure_ascii=False)}"

    project_id = PROJECT_ID or graph.get("project_id", "")
    group_id   = GROUP_ID   or graph.get("group_id", "")

    return {
        "task_id":    task_id,
        "title":      task_def["title"],
        "owner":      task_def.get("owner", ""),
        "priority":   task_def.get("priority", "normal"),
        "status":     status,
        "group":      group_id,
        "spec_id":    task_def.get("spec_id", f"{project_id}"),
        "description": description,
        "deadline":   task_def.get("deadline", ""),
        "depends_on": task_def.get("depends_on", []),
        "tags":       all_tags,
    }


# ─── 主逻辑 ───────────────────────────────────────────────────────────────────

def seed(task_graph_path: Path, dry_run: bool = False) -> int:
    """
    读取 task_graph.yaml，逐一创建任务到 task_manager。
    返回失败任务数（0 = 全部成功）。
    """
    if not task_graph_path.exists():
        log.error("task_graph 文件不存在: %s", task_graph_path)
        return 1

    graph = load_task_graph(task_graph_path)
    tasks = graph.get("tasks", [])
    initial_ready = graph.get("initial_ready_set", [])

    log.info("加载 task_graph: %d 个任务，初始 READY: %s",
             len(tasks), initial_ready)

    if dry_run:
        log.info("[dry-run] 跳过 IPC 写入，仅验证格式")
        for t in tasks:
            tm_task = build_tm_task(t, graph)
            log.info("  [dry-run] %s → status=%s tags=%s depends_on=%s",
                     tm_task["task_id"], tm_task["status"],
                     tm_task["tags"], tm_task["depends_on"])
        return 0

    # 检查 IPC socket 是否可达
    if not Path(IPC_SOCKET).exists():
        log.error("IPC socket 不存在: %s（brain_ipc 是否已启动？）", IPC_SOCKET)
        return 1

    client = IpcClient(IPC_SOCKET, SENDER_NAME)
    failures = []

    # 按 depends_on 拓扑顺序写入（简单的依赖优先排序）
    ordered = _topo_sort(tasks)

    for task_def in ordered:
        tm_task = build_tm_task(task_def, graph)
        task_id = tm_task["task_id"]
        try:
            resp = client.task_create(tm_task)
            if resp.get("status") == "ok" or resp.get("task_id") == task_id:
                log.info("✓ %s (%s)", task_id, tm_task["title"][:50])
            else:
                log.error("✗ %s: %s", task_id, resp)
                failures.append(task_id)
        except Exception as e:
            log.error("✗ %s: IPC 异常 — %s", task_id, e)
            failures.append(task_id)

    if failures:
        log.error("失败任务（%d/%d）: %s", len(failures), len(tasks), failures)
        return 2

    # 写入 seeding 记录（供 bootstrap_verification_report 引用）
    _write_seeding_record(task_graph_path, graph, len(tasks))
    log.info("seeding 完成：%d 个任务已写入 task_manager", len(tasks))
    return 0


def _topo_sort(tasks: list[dict]) -> list[dict]:
    """
    简单拓扑排序：确保 depends_on 中的任务先于依赖它的任务创建。
    task_manager 在 TASK_CREATE 时不校验依赖是否存在，但顺序正确更清晰。
    """
    by_id = {t["task_id"]: t for t in tasks}
    visited: set[str] = set()
    result: list[dict] = []

    def visit(tid: str) -> None:
        if tid in visited:
            return
        visited.add(tid)
        task = by_id.get(tid)
        if not task:
            return
        for dep in task.get("depends_on", []):
            visit(dep)
        result.append(task)

    for t in tasks:
        visit(t["task_id"])
    return result


def _write_seeding_record(task_graph_path: Path, graph: dict, count: int) -> None:
    """写入 seeding 完成记录，供 bootstrap_verification_report 引用"""
    record = {
        "seeded_at": datetime.now(timezone.utc).isoformat(),
        "task_graph_ref": str(task_graph_path),
        "project_id": graph.get("project_id", ""),
        "task_count": count,
        "initial_ready_set": graph.get("initial_ready_set", []),
        "status": "completed",
    }
    record_path = task_graph_path.parent / "task_graph_seeding_record.yaml"
    with open(record_path, "w", encoding="utf-8") as f:
        yaml.dump(record, f, allow_unicode=True, sort_keys=False)
    log.info("seeding 记录已写入: %s", record_path)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="将 task_graph.yaml 写入 brain_task_manager"
    )
    parser.add_argument(
        "--task-graph",
        required=True,
        help="task_graph.yaml 路径（task_modeling 产出）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证格式，不写入 task_manager",
    )
    args = parser.parse_args()

    exit_code = seed(Path(args.task_graph), dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
