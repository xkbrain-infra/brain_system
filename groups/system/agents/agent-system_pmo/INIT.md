# PMO INIT (Brain System)

适用范围: `/brain/groups/org/brain_system`  
角色: `agent_system_pmo`

## 启动检查

1. 确认 `brain_ipc` 在线（`/tmp/brain_ipc.sock` 可连通）。
2. 确认 `service-task_manager` 在线并可收发 IPC。
3. 立项后必须存在 `spec_id` 与 `06_tasks.yaml`。

## 派发硬门禁（必须）

在将任务推进到 `in_progress` 前，必须按顺序完成：

1. `PROJECT_DEPENDENCY_SET`
2. `TASK_STATS`
3. `TASK_PIPELINE_CHECK`（必须 `valid=true`）
4. `TASK_UPDATE -> in_progress`

禁止跳过任何一步。

## 标准执行入口（唯一推荐）

使用一键脚本执行上述完整流程：

```bash
python3 /brain/infrastructure/service/task_manager/scripts/pmo_dispatch_guard.py \
  --requester agent_system_pmo \
  --project-id <SPEC_ID> \
  --task-id <TASK_ID> \
  --depends-on <UPSTREAM_SPEC_ID>
```

仅预检（不派发）：

```bash
python3 /brain/infrastructure/service/task_manager/scripts/pmo_dispatch_guard.py \
  --requester agent_system_pmo \
  --project-id <SPEC_ID> \
  --precheck-only
```

## 失败处理

- 若脚本返回非 0，视为门禁未通过，禁止派发。
- 优先修复 `TASK_PIPELINE_CHECK` 的 `missing_dependencies / flow_violations / cycle_detected`。
- 修复后重新执行脚本，直到返回 `status=ok`。
