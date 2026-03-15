# brain-ipc-c

`brain-ipc-c` is a C implementation of the Brain IPC MCP server. It exposes the same tool surface as `brain-ipc` (Python) and additionally relays daemon wake-up events as MCP `notifications/message` so agents can call `ipc_recv` without polling.

## Directory Structure

```
brain_ipc_c/
├── src/           # Source files (.c, .h)
├── build/         # Compiled object files (.o)
├── bin/           # Executable binary
├── Makefile       # Build configuration
└── README.md      # This file
```

## Build

From this directory:

```bash
make
```

The compiled binary will be placed in `bin/brain_ipc_c_mcp_server`.

## Runtime

This server talks to the daemon socket:

- `BRAIN_IPC_SOCKET` (default: `/tmp/brain_ipc.sock`)

and listens for daemon wake-up events via:

- `BRAIN_IPC_NOTIFY_SOCKET` (default: `/tmp/brain_ipc_notify.sock`)

Notifications are wake-up only; payload must be fetched via `ipc_recv`.

