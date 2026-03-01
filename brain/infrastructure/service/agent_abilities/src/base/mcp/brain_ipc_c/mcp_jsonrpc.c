#include "mcp_jsonrpc.h"

#include <stdlib.h>
#include <string.h>

static void write_json_line_locked(McpJsonRpc *m, json_t *obj) {
  char *s = json_dumps(obj, JSON_COMPACT);
  if (!s) return;
  pthread_mutex_lock(m->out_mu);
  fputs(s, m->out);
  fputc('\n', m->out);
  fflush(m->out);
  pthread_mutex_unlock(m->out_mu);
  free(s);
}

void mcp_jsonrpc_init(McpJsonRpc *m, FILE *out, pthread_mutex_t *out_mu, const char *name, const char *version) {
  m->out = out;
  m->out_mu = out_mu;
  m->server_name = name;
  m->server_version = version;
}

void mcp_send_response(McpJsonRpc *m, json_t *id, json_t *result) {
  json_t *resp = json_object();
  json_object_set_new(resp, "jsonrpc", json_string("2.0"));
  json_object_set(resp, "id", id ? id : json_null());
  json_object_set(resp, "result", result ? result : json_object());
  write_json_line_locked(m, resp);
  json_decref(resp);
}

void mcp_send_error(McpJsonRpc *m, json_t *id, int code, const char *message) {
  json_t *err = json_object();
  json_object_set_new(err, "code", json_integer(code));
  json_object_set_new(err, "message", json_string(message ? message : "error"));

  json_t *resp = json_object();
  json_object_set_new(resp, "jsonrpc", json_string("2.0"));
  json_object_set(resp, "id", id ? id : json_null());
  json_object_set_new(resp, "error", err);
  write_json_line_locked(m, resp);
  json_decref(resp);
}


