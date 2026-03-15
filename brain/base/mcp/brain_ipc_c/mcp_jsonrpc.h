#pragma once

#include <jansson.h>
#include <pthread.h>
#include <stdio.h>

typedef struct {
  FILE *out;
  pthread_mutex_t *out_mu;
  const char *server_name;
  const char *server_version;
} McpJsonRpc;

void mcp_jsonrpc_init(McpJsonRpc *m, FILE *out, pthread_mutex_t *out_mu, const char *name, const char *version);

/* Response helpers */
void mcp_send_response(McpJsonRpc *m, json_t *id, json_t *result);
void mcp_send_error(McpJsonRpc *m, json_t *id, int code, const char *message);

