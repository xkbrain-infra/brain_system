#pragma once

#include "daemon_client.h"

typedef struct {
  const char *notify_socket_path;
  const char *agent_id;
  const char *agent_name;
  DaemonClient *dc; /* for auto re-register on daemon restart */
  volatile int *shutdown_flag;
} NotifyBridge;

/* Starts a background thread that connects to daemon notify socket.
   On daemon reconnect, re-registers the agent. No MCP notifications are sent. */
int notify_bridge_start(NotifyBridge *b);

