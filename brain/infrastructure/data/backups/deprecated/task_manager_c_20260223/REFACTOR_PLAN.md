# Service Task Manager Refactoring Plan

## Current Status (2026-02-20)
- **Status:** Operational
- **Fixes Applied:**
    - Corrected directory paths in configuration and source code (`task-manager` -> `task_manager`).
    - Added `test` target to Makefile.
    - Verified functionality with smoke tests.

## Goals
To ensure this service meets the high reliability and scalability expectations ("Huge Hopes"), the following improvements are planned:

### Phase 1: Robustness (High Priority)
- [ ] **Recursive Directory Creation:** Implement `mkdir_p` to automatically create full directory paths on startup.
- [ ] **JSON Configuration:** Migrate from ad-hoc YAML parsing to `libjansson` for configuration to match IPC standards and improve reliability.
- [ ] **Enhanced Logging:** 
    - Log to stdout/stderr in addition to file (configurable).
    - detailed error reporting (errno/strerror) for all system calls.

### Phase 2: Modularization (Medium Priority)
- [ ] **Extract Components:** Split `service_task_manager.c` into:
    - `src/ipc_client.c`: Encapsulate all interaction with `brain_ipc`.
    - `src/health_server.c`: Isolate health check HTTP server logic.
    - `src/scheduler.c`: Move deadline and stale check logic.
    - `src/config.c`: centralized config loading and validation.

### Phase 3: Features & scaling (Future)
- [ ] **State Persistence:** Evaluate if JSON flat files (`tasks.json`) are sufficient or if SQLite/LevelDB is needed for larger datasets.
- [ ] **Metrics:** Expose more granular Prometheus-compatible metrics.
- [ ] **Hot Reload:** Support reloading configuration without restart (SIGHUP).

## Usage
- **Build:** `make`
- **Test:** `make test`
- **Run:** `./build/service-task_manager [config_path]`
