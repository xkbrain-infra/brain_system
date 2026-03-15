#pragma once

#include <jansson.h>

typedef struct {
  const char *socket_path; /* e.g. /tmp/brain_ipc.sock */
} DaemonClient;

void daemon_client_init(DaemonClient *c, const char *socket_path);

/* Sends {"action":..., "data":...}\n and returns parsed JSON object (owned by caller). */
json_t *daemon_request(DaemonClient *c, const char *action, json_t *data, char **err_out);

