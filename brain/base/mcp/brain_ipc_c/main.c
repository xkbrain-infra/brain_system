#include "daemon_client.h"
#include "mcp_jsonrpc.h"
#include "notify_bridge.h"
#include "tmux_detect.h"

#include <errno.h>
#include <fcntl.h>
#include <jansson.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/* Defaults */
#define DAEMON_SOCKET_DEFAULT "/tmp/brain_ipc.sock"
#define DAEMON_START_BIN "/brain/infrastructure/service/brain_ipc/releases/v1.0.0/bin/brain_ipc"
#define DAEMON_NOTIFY_SOCKET_DEFAULT "/tmp/brain_ipc_notify.sock"

static volatile int g_shutdown = 0;

static void on_sig(int sig) {
  (void)sig;
  g_shutdown = 1;
  close(STDIN_FILENO); /* unblock fgets() in main loop */
}

static int socket_exists(const char *p) {
  struct stat st;
  return (p && stat(p, &st) == 0);
}

/* Resolve daemon binary path via current symlink */
static const char *resolve_daemon_bin(void) {
  static char path[512];
  const char *current_link = "/brain/infrastructure/service/brain_ipc/bin/current";
  char link_buf[256];
  ssize_t len = readlink(current_link, link_buf, sizeof(link_buf) - 1);
  if (len > 0) {
    link_buf[len] = '\0';
    snprintf(path, sizeof(path), "/brain/infrastructure/service/brain_ipc/%s/bin/brain_ipc", link_buf);
    if (access(path, X_OK) == 0) return path;
  }
  return DAEMON_START_BIN;
}

static void maybe_autostart_daemon(const char *sock) {
  /* Ignore BRAIN_DAEMON_SOCKET env var, use BRAIN_IPC_SOCKET only.
     Autostart is opt-in to avoid duplicate daemon instances in supervised envs. */
  const char *autostart = getenv("BRAIN_DAEMON_AUTOSTART");
  if (!autostart ||
      !(strcmp(autostart, "1") == 0 || strcasecmp(autostart, "true") == 0 || strcasecmp(autostart, "yes") == 0))
    return;
  if (socket_exists(sock)) return;

  const char *daemon_bin = resolve_daemon_bin();
  if (access(daemon_bin, X_OK) != 0) return;

  char cmd[600];
  snprintf(cmd, sizeof(cmd), "%s start >/dev/null 2>&1", daemon_bin);
  (void)system(cmd);
  for (int i = 0; i < 50; i++) {
    if (socket_exists(sock)) return;
    usleep(100 * 1000);
  }
}

static int is_valid_brain_agent_name(const char *name) {
  /* Valid names: agent_*, service_*, or simple identifiers without dots.
     Invalid: root.codex, user.name (Codex auth identity leaked as env var) */
  if (!name || !name[0]) return 0;
  if (strchr(name, '.')) return 0;  /* e.g. root.codex */
  return 1;
}

static void build_agent_ids(char *agent_name, size_t agent_name_sz, char *agent_id, size_t agent_id_sz) {
  const char *session = tmux_get_session_name();
  const char *name = NULL;

  /* Priority 1: tmux session name (authoritative, controlled by agentctl) */
  /* Support both agent_ (underscore) and agent- (dash) prefixes */
  if (session && session[0] && (strncmp(session, "agent_", 6) == 0 || strncmp(session, "agent-", 7) == 0)) {
    name = session;
  }

  /* Priority 2: BRAIN_AGENT_NAME env (for non-tmux contexts like CLI) */
  if (!name) {
    const char *env_name = getenv("BRAIN_AGENT_NAME");
    if (is_valid_brain_agent_name(env_name)) {
      name = env_name;
    }
  }

  /* Priority 3: last resort fallback */
  if (!name) {
    name = (session && session[0]) ? session : "claude";
  }
  snprintf(agent_name, agent_name_sz, "%s", name);

  const char *pane = tmux_get_pane_id();
  if (pane && pane[0]) {
    snprintf(agent_id, agent_id_sz, "%s@%s:%s", name, session && session[0] ? session : "", pane);
  } else if (session && session[0]) {
    snprintf(agent_id, agent_id_sz, "%s@%s", name, session);
  } else {
    /* Non-tmux context: append timestamp for unique instance_id */
    snprintf(agent_id, agent_id_sz, "%s_%ld", name, (long)time(NULL));
  }
}

static json_t *text_block(const char *text) {
  json_t *b = json_object();
  json_object_set_new(b, "type", json_string("text"));
  json_object_set_new(b, "text", json_string(text ? text : ""));
  return b;
}

static const char *json_str_or_empty(json_t *obj, const char *key) {
  if (!obj || !json_is_object(obj) || !key) return "";
  const char *v = json_string_value(json_object_get(obj, key));
  return v ? v : "";
}

static void truncate_copy(char *dst, size_t dst_sz, const char *src) {
  if (!dst || dst_sz == 0) return;
  dst[0] = '\0';
  if (!src || !src[0]) return;
  if (dst_sz <= 1) return;
  size_t max_copy = dst_sz - 1;
  size_t n = strlen(src);
  if (n <= max_copy) {
    memcpy(dst, src, n);
    dst[n] = '\0';
    return;
  }
  if (max_copy <= 3) {
    memcpy(dst, src, max_copy);
    dst[max_copy] = '\0';
    return;
  }
  size_t keep = max_copy - 3;
  memcpy(dst, src, keep);
  memcpy(dst + keep, "...", 3);
  dst[keep + 3] = '\0';
}

static const char *build_tool_summary(char *buf, size_t buf_sz, const char *tool_name, json_t *structured, int is_error) {
  if (!buf || buf_sz == 0) return is_error ? "error" : "ok";
  buf[0] = '\0';

  if (is_error) return "error";
  if (!tool_name || strcmp(tool_name, "ipc_recv") != 0) return "ok";
  if (!structured || !json_is_object(structured)) return "ok";

  int count = (int)json_integer_value(json_object_get(structured, "count"));
  if (count <= 0) {
    snprintf(buf, buf_sz, "ok: received 0 messages");
    return buf;
  }

  int written = snprintf(buf, buf_sz, "ok: received %d message%s", count, count == 1 ? "" : "s");
  if (written < 0 || (size_t)written >= buf_sz) return buf;

  json_t *msgs = json_object_get(structured, "messages");
  if (!msgs || !json_is_array(msgs)) return buf;

  size_t total = json_array_size(msgs);
  size_t preview = total < 3 ? total : 3;
  for (size_t i = 0; i < preview; i++) {
    json_t *m = json_array_get(msgs, i);
    if (!m || !json_is_object(m)) continue;
    const char *from = json_str_or_empty(m, "from");
    const char *msg_id = json_str_or_empty(m, "msg_id");
    json_t *payload = json_object_get(m, "payload");
    const char *content = json_str_or_empty(payload, "content");
    char content_snip[161];
    truncate_copy(content_snip, sizeof(content_snip), content);
    int n = snprintf(
        buf + written,
        buf_sz - (size_t)written,
        "\n[%zu] from=%s msg_id=%s content=%s",
        i + 1,
        from[0] ? from : "-",
        msg_id[0] ? msg_id : "-",
        content_snip[0] ? content_snip : "(empty)");
    if (n < 0) break;
    written += n;
    if ((size_t)written >= buf_sz) {
      buf[buf_sz - 1] = '\0';
      break;
    }
  }

  if (total > preview && (size_t)written < buf_sz) {
    snprintf(buf + written, buf_sz - (size_t)written, "\n... and %zu more", total - preview);
  }
  return buf;
}

static json_t *call_tool_to_content(json_t *structured, int is_error, const char *tool_name) {
  json_t *res = json_object();
  json_t *arr = json_array();

  /* Primary: JSON dump of structured result for machine-readable parsing */
  if (structured) {
    char *json_str = json_dumps(structured, JSON_COMPACT | JSON_ENSURE_ASCII);
    if (json_str) {
      json_array_append_new(arr, text_block(json_str));
      free(json_str);
    }
  } else {
    char summary[4096];
    const char *summary_text = build_tool_summary(summary, sizeof(summary), tool_name, structured, is_error);
    json_array_append_new(arr, text_block(summary_text));
  }

  json_object_set_new(res, "content", arr);
  /* NOTE: structuredContent removed — Codex SDK rejects non-standard fields */
  json_object_set_new(res, "isError", json_boolean(is_error ? 1 : 0));
  return res;
}

static json_t *schema_obj(void) {
  json_t *o = json_object();
  json_object_set_new(o, "type", json_string("object"));
  json_object_set_new(o, "properties", json_object());
  return o;
}

static void schema_prop(json_t *schema, const char *name, json_t *prop_schema) {
  json_t *props = json_object_get(schema, "properties");
  if (!props || !json_is_object(props)) return;
  json_object_set_new(props, name, prop_schema);
}

static json_t *schema_string(const char *desc) {
  json_t *s = json_object();
  json_object_set_new(s, "type", json_string("string"));
  if (desc && desc[0]) json_object_set_new(s, "description", json_string(desc));
  return s;
}

static json_t *schema_number(const char *desc) {
  json_t *s = json_object();
  json_object_set_new(s, "type", json_string("number"));
  if (desc && desc[0]) json_object_set_new(s, "description", json_string(desc));
  return s;
}

static json_t *schema_bool(const char *desc) {
  json_t *s = json_object();
  json_object_set_new(s, "type", json_string("boolean"));
  if (desc && desc[0]) json_object_set_new(s, "description", json_string(desc));
  return s;
}

static json_t *schema_enum(const char *type, const char **values, size_t n, const char *desc) {
  json_t *s = json_object();
  json_object_set_new(s, "type", json_string(type));
  json_t *arr = json_array();
  for (size_t i = 0; i < n; i++) json_array_append_new(arr, json_string(values[i]));
  json_object_set_new(s, "enum", arr);
  if (desc && desc[0]) json_object_set_new(s, "description", json_string(desc));
  return s;
}

static void schema_required(json_t *schema, const char **names, size_t n) {
  json_t *arr = json_array();
  for (size_t i = 0; i < n; i++) json_array_append_new(arr, json_string(names[i]));
  json_object_set_new(schema, "required", arr);
}

static json_t *tool_list(void) {
  /* Keep in sync with python brain-ipc server tool surface (subset). */
  json_t *tools = json_array();

  /* Helper macro */
  #define ADD_TOOL(_name,_desc,_schema) do { \
    json_t *t = json_object(); \
    json_object_set_new(t, "name", json_string((_name))); \
    json_object_set_new(t, "description", json_string((_desc))); \
    json_object_set(t, "inputSchema", (_schema)); \
    json_array_append_new(tools, t); \
  } while(0)

  json_t *send_schema = schema_obj();
  schema_prop(send_schema, "to", schema_string("Target agent name"));
  schema_prop(send_schema, "message", schema_string("Message content"));
  schema_prop(send_schema, "conversation_id", schema_string("Optional conversation ID"));
  {
    const char *vals[] = {"request", "response", "final"};
    schema_prop(send_schema, "message_type", schema_enum("string", vals, 3, "Message type"));
  }
  {
    const char *vals[] = {"critical", "high", "normal", "low"};
    schema_prop(send_schema, "priority", schema_enum("string", vals, 4, "Expected response urgency"));
  }
  schema_prop(send_schema, "priority_reason", schema_string("Optional reason for priority level"));
  {
    const char *reqs[] = {"to", "message"};
    schema_required(send_schema, reqs, 2);
  }
  ADD_TOOL("ipc_send", "Send message to another agent", send_schema);

  json_t *delayed_schema = schema_obj();
  schema_prop(delayed_schema, "to", schema_string("Target agent (can be self)"));
  schema_prop(delayed_schema, "message", schema_string("Message content"));
  schema_prop(delayed_schema, "delay_seconds", schema_number("Delay in seconds (1-86400)"));
  schema_prop(delayed_schema, "conversation_id", schema_string("Optional conversation ID"));
  {
    const char *vals[] = {"response", "final"};
    schema_prop(delayed_schema, "message_type", schema_enum("string", vals, 2, "Message type"));
  }
  {
    const char *reqs[] = {"to", "message", "delay_seconds"};
    schema_required(delayed_schema, reqs, 3);
  }
  ADD_TOOL("ipc_send_delayed", "Send delayed message", delayed_schema);

  json_t *recv_schema = schema_obj();
  schema_prop(recv_schema, "conversation_id", schema_string("Optional filter by conversation"));
  schema_prop(recv_schema, "message_id", schema_string("Optional exact msg_id from an [IPC] notification. When set, fetch that specific message across the agent's queues."));
  schema_prop(recv_schema, "wait_seconds", schema_number("Long-poll: block up to N seconds if no messages (0=immediate, max 120). Recommended: 30"));
  ADD_TOOL("ipc_recv", "Receive messages. Supports long-poll via wait_seconds to avoid busy-loop polling.", recv_schema);

  json_t *conv_schema = schema_obj();
  schema_prop(conv_schema, "participants", schema_string("Comma-separated agent names"));
  schema_prop(conv_schema, "metadata", schema_string("Optional JSON metadata"));
  {
    const char *reqs[] = {"participants"};
    schema_required(conv_schema, reqs, 1);
  }
  ADD_TOOL("conversation_create", "Create a new multi-turn conversation", conv_schema);

  json_t *reg_schema = schema_obj();
  schema_prop(reg_schema, "agent_name", schema_string("Agent name (defaults to BRAIN_AGENT_NAME env)"));
  schema_prop(reg_schema, "metadata", schema_string("Optional JSON metadata"));
  ADD_TOOL("ipc_register", "Register this agent as online", reg_schema);

  json_t *list_schema = schema_obj();
  schema_prop(list_schema, "include_offline", schema_bool("Include offline/stale agents (default: false)"));
  ADD_TOOL("ipc_list_agents", "List all registered agents", list_schema);

  json_t *service_list_schema = schema_obj();
  schema_prop(service_list_schema, "include_offline", schema_bool("Include offline/stale services (default: false)"));
  ADD_TOOL("ipc_list_services", "List registered services", service_list_schema);

  json_t *search_schema = schema_obj();
  schema_prop(search_schema, "query", schema_string("Search keyword"));
  {
    const char *vals[] = {"all", "agent", "service", "register", "heartbeat", "tmux_discovery"};
    schema_prop(search_schema, "source", schema_enum("string", vals, 6, "Source filter (default: all)"));
  }
  schema_prop(search_schema, "fuzzy", schema_bool("Enable fuzzy match (default: true)"));
  schema_prop(search_schema, "include_offline", schema_bool("Include offline entries (default: false)"));
  schema_prop(search_schema, "limit", schema_number("Maximum results (default: 50, max: 512)"));
  {
    const char *reqs[] = {"query"};
    schema_required(search_schema, reqs, 1);
  }
  ADD_TOOL("ipc_search", "Search IPC registry entries", search_schema);

  #undef ADD_TOOL
  return tools;
}

static json_t *handle_tools_call(DaemonClient *dc, const char *agent_id, const char *agent_name, const char *tool, json_t *args, char **err_out) {
  if (err_out) *err_out = NULL;
  if (!tool) return NULL;

  if (strcmp(tool, "ipc_send") == 0) {
    const char *to = json_string_value(json_object_get(args, "to"));
    const char *message = json_string_value(json_object_get(args, "message"));
    const char *conversation_id = json_string_value(json_object_get(args, "conversation_id"));
    const char *message_type = json_string_value(json_object_get(args, "message_type"));
    const char *priority = json_string_value(json_object_get(args, "priority"));
    const char *priority_reason = json_string_value(json_object_get(args, "priority_reason"));
    if (!to || !message) {
      if (err_out) *err_out = strdup("missing to/message");
      return NULL;
    }
    json_t *payload = json_object();
    json_object_set_new(payload, "content", json_string(message));
    if (priority && priority[0]) json_object_set_new(payload, "priority", json_string(priority));
    if (priority_reason && priority_reason[0]) json_object_set_new(payload, "priority_reason", json_string(priority_reason));

    json_t *data = json_object();
    json_object_set_new(data, "from", json_string(agent_id));
    json_object_set_new(data, "to", json_string(to));
    json_object_set_new(data, "payload", payload);
    if (conversation_id && conversation_id[0]) json_object_set_new(data, "conversation_id", json_string(conversation_id));
    if (message_type && message_type[0]) json_object_set_new(data, "message_type", json_string(message_type));
    json_t *resp = daemon_request(dc, "ipc_send", data, err_out);
    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "ipc_send_delayed") == 0) {
    const char *to = json_string_value(json_object_get(args, "to"));
    const char *message = json_string_value(json_object_get(args, "message"));
    json_t *delay_v = json_object_get(args, "delay_seconds");
    const char *conversation_id = json_string_value(json_object_get(args, "conversation_id"));
    const char *message_type = json_string_value(json_object_get(args, "message_type"));
    if (!to || !message || !delay_v) {
      if (err_out) *err_out = strdup("missing to/message/delay_seconds");
      return NULL;
    }
    int delay_seconds = (int)json_number_value(delay_v);
    json_t *payload = json_object();
    json_object_set_new(payload, "content", json_string(message));

    json_t *data = json_object();
    json_object_set_new(data, "from", json_string(agent_id));
    json_object_set_new(data, "to", json_string(to));
    json_object_set_new(data, "payload", payload);
    json_object_set_new(data, "delay_seconds", json_integer(delay_seconds));
    if (conversation_id && conversation_id[0]) json_object_set_new(data, "conversation_id", json_string(conversation_id));
    if (message_type && message_type[0]) json_object_set_new(data, "message_type", json_string(message_type));
    json_t *resp = daemon_request(dc, "ipc_send_delayed", data, err_out);
    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "ipc_recv") == 0) {
    const char *conversation_id = json_string_value(json_object_get(args, "conversation_id"));
    const char *message_id = json_string_value(json_object_get(args, "message_id"));
    json_t *wait_v = json_object_get(args, "wait_seconds");
    int wait_seconds = wait_v ? (int)json_number_value(wait_v) : 0;
    if (wait_seconds < 0) wait_seconds = 0;
    if (wait_seconds > 120) wait_seconds = 120;

    json_t *data = json_object();
    json_object_set_new(data, "agent", json_string(agent_id));
    if (conversation_id && conversation_id[0]) json_object_set_new(data, "conversation_id", json_string(conversation_id));
    if (message_id && message_id[0]) json_object_set_new(data, "message_id", json_string(message_id));
    /* Always auto mode - recv = consume */
    json_object_set_new(data, "max_items", json_integer(100));
    json_t *resp = daemon_request(dc, "ipc_recv", data, err_out);

    /* Long-poll: if no messages and wait_seconds > 0, listen on notify socket */
    if (wait_seconds > 0 && resp && json_is_object(resp)) {
      json_t *count_v = json_object_get(resp, "count");
      int count = count_v ? (int)json_integer_value(count_v) : 0;
      if (count == 0) {
        json_decref(resp);
        resp = NULL;
        /* Connect to notify socket and wait for a message addressed to us */
        const char *nsock = getenv("BRAIN_IPC_NOTIFY_SOCKET");
        if (!nsock || !nsock[0]) nsock = DAEMON_NOTIFY_SOCKET_DEFAULT;
        int nfd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (nfd >= 0) {
          struct sockaddr_un naddr;
          memset(&naddr, 0, sizeof(naddr));
          naddr.sun_family = AF_UNIX;
          strncpy(naddr.sun_path, nsock, sizeof(naddr.sun_path) - 1);
          if (connect(nfd, (struct sockaddr *)&naddr, sizeof(naddr)) == 0) {
            struct timeval tv;
            tv.tv_sec = wait_seconds;
            tv.tv_usec = 0;
            setsockopt(nfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
            char nbuf[4096];
            ssize_t nr = read(nfd, nbuf, sizeof(nbuf) - 1);
            (void)nr;
          }
          close(nfd);
        }
        /* Re-issue ipc_recv after wake-up or timeout */
        json_t *data2 = json_object();
        json_object_set_new(data2, "agent", json_string(agent_id));
        if (conversation_id && conversation_id[0]) json_object_set_new(data2, "conversation_id", json_string(conversation_id));
        if (message_id && message_id[0]) json_object_set_new(data2, "message_id", json_string(message_id));
        json_object_set_new(data2, "max_items", json_integer(100));
        resp = daemon_request(dc, "ipc_recv", data2, err_out);
        json_decref(data2);
      }
    }

    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "conversation_create") == 0) {
    const char *participants = json_string_value(json_object_get(args, "participants"));
    const char *metadata_s = json_string_value(json_object_get(args, "metadata"));
    json_t *metadata = NULL;
    if (metadata_s && metadata_s[0]) {
      json_error_t jerr;
      metadata = json_loads(metadata_s, 0, &jerr);
    }
    if (!participants || !participants[0]) {
      if (metadata) json_decref(metadata);
      if (err_out) *err_out = strdup("missing participants");
      return NULL;
    }
    json_t *data = json_object();
    json_object_set_new(data, "participants", json_string(participants));
    if (metadata && json_is_object(metadata)) {
      json_object_set(data, "metadata", metadata);
    } else {
      json_object_set_new(data, "metadata", json_object());
    }
    if (metadata) json_decref(metadata);
    json_t *resp = daemon_request(dc, "conversation_create", data, err_out);
    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "ipc_register") == 0) {
    /* Always use the server's own agent_name from BRAIN_AGENT_NAME env.
       Ignore user-provided agent_name to prevent identity mismatch. */
    const char *metadata_s = json_string_value(json_object_get(args, "metadata"));
    json_t *metadata = NULL;
    if (metadata_s && metadata_s[0]) {
      json_error_t jerr;
      metadata = json_loads(metadata_s, 0, &jerr);
    }
    const char *pane = tmux_get_pane_id();
    const char *session = tmux_get_session_name();
    if (pane && pane[0]) {
      /* tmux agent: use agent_register with pane info */
      json_t *data = json_object();
      json_object_set_new(data, "agent_name", json_string(agent_name));
      json_object_set_new(data, "tmux_pane", json_string(pane));
      if (session && session[0]) json_object_set_new(data, "tmux_session", json_string(session));
      json_object_set(data, "metadata", (metadata && json_is_object(metadata)) ? metadata : json_object());
      if (metadata) json_decref(metadata);
      json_t *resp = daemon_request(dc, "agent_register", data, err_out);
      json_decref(data);
      return resp;
    } else {
      /* Non-tmux: register as service */
      json_t *data = json_object();
      json_object_set_new(data, "service_name", json_string(agent_name));
      json_object_set(data, "metadata", (metadata && json_is_object(metadata)) ? metadata : json_object());
      if (metadata) json_decref(metadata);
      json_t *resp = daemon_request(dc, "service_register", data, err_out);
      json_decref(data);
      return resp;
    }
  }

  if (strcmp(tool, "ipc_list_agents") == 0) {
    int include_offline = json_is_true(json_object_get(args, "include_offline")) ? 1 : 0;
    json_t *data = json_object();
    json_object_set_new(data, "include_offline", json_boolean(include_offline));
    json_t *resp = daemon_request(dc, "agent_list", data, err_out);
    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "ipc_list_services") == 0) {
    int include_offline = json_is_true(json_object_get(args, "include_offline")) ? 1 : 0;
    json_t *data = json_object();
    json_object_set_new(data, "include_offline", json_boolean(include_offline));
    json_t *resp = daemon_request(dc, "service_list", data, err_out);
    json_decref(data);
    return resp;
  }

  if (strcmp(tool, "ipc_search") == 0) {
    const char *query = json_string_value(json_object_get(args, "query"));
    if (!query || !query[0]) {
      if (err_out) *err_out = strdup("missing query");
      return NULL;
    }
    const char *source = json_string_value(json_object_get(args, "source"));
    int fuzzy = json_object_get(args, "fuzzy") && json_is_false(json_object_get(args, "fuzzy")) ? 0 : 1;
    int include_offline = json_is_true(json_object_get(args, "include_offline")) ? 1 : 0;
    json_t *limit_v = json_object_get(args, "limit");
    int limit = limit_v ? (int)json_number_value(limit_v) : 50;
    if (limit <= 0) limit = 50;
    if (limit > 512) limit = 512;

    json_t *data = json_object();
    json_object_set_new(data, "query", json_string(query));
    json_object_set_new(data, "source", json_string((source && source[0]) ? source : "all"));
    json_object_set_new(data, "fuzzy", json_boolean(fuzzy));
    json_object_set_new(data, "include_offline", json_boolean(include_offline));
    json_object_set_new(data, "limit", json_integer(limit));
    json_t *resp = daemon_request(dc, "registry_search", data, err_out);
    json_decref(data);
    return resp;
  }

  (void)agent_name;
  if (err_out) *err_out = strdup("unknown tool");
  return NULL;
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  signal(SIGINT, on_sig);
  signal(SIGTERM, on_sig);

  const char *daemon_sock = getenv("BRAIN_IPC_SOCKET");
  if (!daemon_sock || !daemon_sock[0]) daemon_sock = DAEMON_SOCKET_DEFAULT;

  const char *notify_sock = getenv("BRAIN_IPC_NOTIFY_SOCKET");
  if (!notify_sock || !notify_sock[0]) notify_sock = DAEMON_NOTIFY_SOCKET_DEFAULT;

  maybe_autostart_daemon(daemon_sock);

  char agent_name[64];
  char agent_id[256];
  build_agent_ids(agent_name, sizeof(agent_name), agent_id, sizeof(agent_id));

  pthread_mutex_t out_mu;
  pthread_mutex_init(&out_mu, NULL);
  McpJsonRpc mcp;
  mcp_jsonrpc_init(&mcp, stdout, &out_mu, "brain_ipc", "0.1");

  DaemonClient dc;
  daemon_client_init(&dc, daemon_sock);

  /* Auto-register */
  {
    const char *pane = tmux_get_pane_id();
    const char *session = tmux_get_session_name();
    char *err = NULL;
    json_t *resp = NULL;
    if (pane && pane[0]) {
      /* tmux agent: use agent_register */
      json_t *data = json_object();
      json_object_set_new(data, "agent_name", json_string(agent_name));
      json_object_set_new(data, "metadata", json_pack("{s:s,s:b}", "mcp_type", "mcp-brain_ipc", "auto_registered", 1));
      json_object_set_new(data, "tmux_pane", json_string(pane));
      if (session && session[0]) json_object_set_new(data, "tmux_session", json_string(session));
      resp = daemon_request(&dc, "agent_register", data, &err);
      json_decref(data);
    } else {
      /* Non-tmux: use service_register */
      json_t *data = json_object();
      json_object_set_new(data, "service_name", json_string("mcp-brain_ipc"));
      json_object_set_new(data, "metadata", json_pack("{s:s,s:b}", "agent_name", agent_name, "auto_registered", 1));
      resp = daemon_request(&dc, "service_register", data, &err);
      json_decref(data);
    }
    if (resp) json_decref(resp);
    free(err);
  }

  /* Start notify bridge (reconnect detection only) */
  NotifyBridge b = {.notify_socket_path = notify_sock, .agent_id = agent_id, .agent_name = agent_name, .dc = &dc, .shutdown_flag = &g_shutdown};
  (void)notify_bridge_start(&b);

  /* Main JSON-RPC loop */
  char line[1 << 20];
  while (!g_shutdown && fgets(line, sizeof(line), stdin)) {
    /* parse */
    json_error_t jerr;
    json_t *req = json_loads(line, 0, &jerr);
    if (!req || !json_is_object(req)) {
      if (req) json_decref(req);
      continue;
    }
    json_t *id = json_object_get(req, "id"); /* borrowed */
    const char *method = json_string_value(json_object_get(req, "method"));
    json_t *params = json_object_get(req, "params");

    if (!method) {
      json_decref(req);
      continue;
    }

    if (strcmp(method, "initialize") == 0) {
      json_t *p = params && json_is_object(params) ? params : json_object();
      json_t *pv = json_object_get(p, "protocolVersion");

      json_t *cap = json_object();
      json_object_set_new(cap, "tools", json_object());
      json_object_set_new(cap, "logging", json_object());

      json_t *info = json_pack("{s:s,s:s}", "name", "brain_ipc", "version", "0.1");
      json_t *res = json_object();
      if (pv) json_object_set(res, "protocolVersion", pv);
      else json_object_set_new(res, "protocolVersion", json_string("1"));
      json_object_set_new(res, "capabilities", cap);
      json_object_set_new(res, "serverInfo", info);
      json_object_set_new(res, "instructions", json_string("Brain IPC tools (C). Uses daemon socket; notifications are wake-up only. Use ipc_recv to fetch payloads."));
      mcp_send_response(&mcp, id, res);
      json_decref(res);
      json_decref(req);
      continue;
    }

    if (strcmp(method, "tools/list") == 0) {
      json_t *res = json_object();
      json_object_set_new(res, "tools", tool_list());
      mcp_send_response(&mcp, id, res);
      json_decref(res);
      json_decref(req);
      continue;
    }

    if (strcmp(method, "tools/call") == 0) {
      const char *name = NULL;
      json_t *args = NULL;
      if (params && json_is_object(params)) {
        name = json_string_value(json_object_get(params, "name"));
        args = json_object_get(params, "arguments");
      }
      if (!name) {
        mcp_send_error(&mcp, id, -32602, "missing params.name");
        json_decref(req);
        continue;
      }
      if (!args || !json_is_object(args)) args = json_object();

      char *err = NULL;
      json_t *structured = handle_tools_call(&dc, agent_id, agent_name, name, args, &err);
      int is_error = 0;
      if (!structured) {
        is_error = 1;
        structured = json_pack("{s:s}", "error", err ? err : "tool call failed");
      }
      json_t *result = call_tool_to_content(structured, is_error, name);
      mcp_send_response(&mcp, id, result);
      json_decref(result);
      json_decref(structured);
      free(err);
      json_decref(req);
      continue;
    }

    if (strcmp(method, "ping") == 0) {
      mcp_send_response(&mcp, id, json_object());
      json_decref(req);
      continue;
    }

    /* notifications/initialized etc: no response required */
    json_decref(req);
  }

  pthread_mutex_destroy(&out_mu);
  return 0;
}
