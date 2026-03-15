# Service Task Manager

Spec/Task lifecycle management service for Brain System.

## Overview

This service manages the lifecycle of Tasks and Specs within the `/brain/groups/org/brain_system` scope. It provides:
- Task creation, update, query, and deletion via IPC.
- Task statistics for linear execution tracking (`TASK_STATS`).
- Task pipeline validation for dependency flow correctness (`TASK_PIPELINE_CHECK`).
- Project dependency graph management (`PROJECT_DEPENDENCY_SET` / `PROJECT_DEPENDENCY_QUERY`).
- Dispatch hard gate: for existing specs, `TASK_UPDATE -> in_progress` is rejected until all three checks are completed.
- Spec lifecycle management (S1-S8).
- Project intake baseline: `SPEC_CREATE` will create an intake task record (`{spec_id}-T001`) and a bootstrap `06_tasks.yaml`.
- Deadline reminders and stale task/spec alerts.
- Health monitoring.

## Directory Structure

- `src/`: Source code (C11).
- `config/`: Configuration files.
- `data/`: Persistent storage (JSON).
- `tests/`: Smoke tests and end-to-end tests.
- `bin/`: Compiled binaries.

## Getting Started

### Prerequisites
- GCC, Make
- libjansson-dev
- brain_ipc daemon running

### Build
```bash
make
```

### Test
```bash
make test
```

### Run
```bash
./bin/service-task_manager config/task_manager.yaml
```

### PMO One-Shot Dispatch
```bash
python3 scripts/pmo_dispatch_guard.py \
  --requester agent_system_pmo \
  --project-id BS-024-file-hierarchy-embedding \
  --task-id BS-024-T3 \
  --depends-on BS-010-foundation
```

This wrapper executes the hard-gate sequence in order:
1. `PROJECT_DEPENDENCY_SET`
2. `TASK_STATS`
3. `TASK_PIPELINE_CHECK` (must be `valid=true`)
4. `TASK_UPDATE -> in_progress`

## Configuration

Configuration is loaded from `config/task_manager.yaml`.
Key settings:
- `data_dir`: Directory for storing tasks.json and specs.json.
- `socket_path`: Path to brain_ipc socket.
- `health_port`: HTTP health check port (default 8091).

## Process Management

Managed by Supervisor.
Config: `/brain/infrastructure/config/supervisord.d/task_manager.conf`
Log: `/brain/runtime/logs/service-task_manager.log`

## Refactoring Status

See [REFACTOR_PLAN.md](REFACTOR_PLAN.md) for current improvement plans.
