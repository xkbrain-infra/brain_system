/*
 * Service Task Manager — 主入口 + IPC 路由
 *
 * 功能:
 *   1. 启动后注册到 daemon (agent_name: service-task_manager)
 *   2. 主循环: ipc_recv → route → handle → respond
 *   3. 定时检查: deadline 提醒, stale task/spec 告警
 *   4. SIGTERM/SIGINT 优雅退出
 *
 * 支持的 IPC 消息:
 *   TASK_CREATE, TASK_UPDATE, TASK_QUERY, TASK_DELETE
 *   SPEC_CREATE, SPEC_PROGRESS, SPEC_QUERY
 *   HEALTH, PING
 */

#include "task_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/select.h>
#include <fcntl.h>
#include <stdarg.h>

/* ── Config ── */
#define DEFAULT_SOCKET       "/tmp/brain_ipc.sock"
#define DEFAULT_NOTIFY_SOCK  "/tmp/brain_ipc_notify.sock"
#define DEFAULT_AGENT_NAME   "service-task_manager"
#define DEFAULT_DATA_DIR     "/brain/infrastructure/service/task-manager/data"
#define DEFAULT_LOG_FILE     "/brain/runtime/logs/service-task_manager.log"
#define SCHEDULER_INTERVAL_S 10     /* scheduler tick interval when idle */
#define DISCONNECTED_POLL_INTERVAL_S 1
#define MAX_RECV_BATCH       10
#define IPC_DRAIN_MAX_ROUNDS 32
#define IPC_ERROR_BACKOFF_US 200000
#define NOTIFY_RECONNECT_BASE_S 1
#define NOTIFY_RECONNECT_MAX_S 30
#define METRICS_LOG_INTERVAL_S 60
#define BUFFER_SIZE          65536

/* ── Global state ── */
static volatile int g_shutdown = 0;
static TaskStore  g_task_store;
static SpecStore  g_spec_store;
static FILE      *g_logfile = NULL;

/* ── Scheduler state ── */
static time_t g_last_deadline_check = 0;
static time_t g_last_stale_task_check = 0;
static time_t g_last_stale_spec_check = 0;
static time_t g_last_heartbeat = 0;
#define HEARTBEAT_INTERVAL 60  /* send heartbeat every 60s */

/* Config values (loaded from YAML or defaults) */
static int cfg_deadline_interval   = 300;
static int cfg_stale_task_interval = 3600;
static int cfg_stale_spec_interval = 3600;
static int cfg_deadline_warning_h  = 24;
static int cfg_stale_task_h        = 48;
static int cfg_stale_spec_h        = 72;

static char cfg_socket_path[512]   = DEFAULT_SOCKET;
static char cfg_agent_name[128]    = DEFAULT_AGENT_NAME;
static char cfg_data_dir[512]      = DEFAULT_DATA_DIR;
static char cfg_log_file[512]      = DEFAULT_LOG_FILE;

typedef struct {
    unsigned long loops;
    unsigned long notify_wakeups;
    unsigned long timeouts;
    unsigned long notify_disconnects;
    unsigned long notify_reconnect_attempts;
    unsigned long notify_reconnect_success;
    unsigned long ipc_recv_calls;
    unsigned long ipc_recv_failures;
    unsigned long ipc_batches_processed;
    unsigned long ipc_messages_processed;
    unsigned long ipc_ack_batches;
} LoopMetrics;

static LoopMetrics g_metrics = {0};
static time_t g_started_at = 0;
static time_t g_last_metrics_log = 0;

/* ── Logging ── */
static void tm_log(const char *level, const char *fmt, ...) {
    if (!g_logfile) return;
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    char ts[32];
    strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &tm);

    fprintf(g_logfile, "[%s] [%s] ", ts, level);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_logfile, fmt, ap);
    va_end(ap);
    fprintf(g_logfile, "\n");
    fflush(g_logfile);
}

/* ── Signal handler ── */
static void on_signal(int sig) {
    (void)sig;
    g_shutdown = 1;
}

/* ── Daemon communication (short-lived connection per request) ── */
static json_t *daemon_call(const char *action, json_t *data) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        tm_log("ERROR", "socket: %s", strerror(errno));
        return NULL;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, cfg_socket_path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        tm_log("ERROR", "connect to daemon: %s", strerror(errno));
        close(fd);
        return NULL;
    }

    /* build request */
    json_t *req = json_object();
    json_object_set_new(req, "action", json_string(action));
    if (data)
        json_object_set(req, "data", data);
    else
        json_object_set_new(req, "data", json_object());

    char *line = json_dumps(req, JSON_COMPACT);
    json_decref(req);
    if (!line) { close(fd); return NULL; }

    /* send line + \n */
    size_t len = strlen(line);
    char *sendbuf = malloc(len + 2);
    memcpy(sendbuf, line, len);
    sendbuf[len] = '\n';
    sendbuf[len + 1] = '\0';
    free(line);

    ssize_t off = 0, total = (ssize_t)(len + 1);
    while (off < total) {
        ssize_t n = write(fd, sendbuf + off, (size_t)(total - off));
        if (n < 0) {
            if (errno == EINTR) continue;
            tm_log("ERROR", "write to daemon: %s", strerror(errno));
            free(sendbuf);
            close(fd);
            return NULL;
        }
        off += n;
    }
    free(sendbuf);

    /* read response line */
    char buf[BUFFER_SIZE];
    size_t used = 0;
    while (used + 1 < sizeof(buf)) {
        char ch;
        ssize_t n = read(fd, &ch, 1);
        if (n == 0) break;
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        buf[used++] = ch;
        if (ch == '\n') break;
    }
    buf[used] = '\0';
    close(fd);

    if (used == 0) return NULL;

    json_error_t err;
    json_t *resp = json_loads(buf, 0, &err);
    return resp;
}

/* ── IPC helpers ── */
static int ipc_register(void) {
    json_t *data = json_object();
    json_object_set_new(data, "service_name", json_string(cfg_agent_name));

    json_t *meta = json_object();
    json_object_set_new(meta, "type", json_string("task_manager"));
    json_object_set_new(data, "metadata", meta);

    json_t *resp = daemon_call("service_register", data);
    json_decref(data);

    int ok = 0;
    if (resp) {
        const char *status = json_string_value(json_object_get(resp, "status"));
        ok = status && strcmp(status, "ok") == 0;
        json_decref(resp);
    }
    return ok;
}

/* ── Notify socket (push-based wake-up) ── */
static int notify_connect(void) {
    const char *path = getenv("BRAIN_NOTIFY_SOCKET");
    if (!path || !path[0]) path = DEFAULT_NOTIFY_SOCK;

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    tm_log("INFO", "connected to notify socket: %s", path);
    return fd;
}

/* Check if notify socket has data; returns 1 if readable, 0 on timeout, -1 on error */
static int notify_wait(int nfd, int timeout_s) {
    if (timeout_s < 0) timeout_s = 0;
    if (nfd < 0) {
        if (timeout_s > 0) sleep((unsigned int)timeout_s);
        return 0;
    }
    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(nfd, &rfds);
    struct timeval tv = { .tv_sec = timeout_s, .tv_usec = 0 };
    return select(nfd + 1, &rfds, NULL, NULL, &tv);
}

/* Drain notify socket buffer (discard data, we only care about wake-up).
 * Returns 0 on success, -1 when peer is gone or on fatal read error. */
static int notify_drain(int nfd) {
    if (nfd < 0) return -1;
    char buf[4096];
    /* Set non-blocking temporarily */
    int flags = fcntl(nfd, F_GETFL, 0);
    if (flags < 0) return -1;
    if (fcntl(nfd, F_SETFL, flags | O_NONBLOCK) < 0) return -1;

    int rc = 0;
    for (;;) {
        ssize_t n = read(nfd, buf, sizeof(buf));
        if (n > 0) continue; /* keep draining */
        if (n == 0) {
            rc = -1; /* peer closed */
            break;
        }
        if (errno == EINTR) continue;
        if (errno == EAGAIN || errno == EWOULDBLOCK) break;
        rc = -1;
        break;
    }
    (void)fcntl(nfd, F_SETFL, flags);
    return rc;
}

static void ipc_heartbeat(void) {
    json_t *data = json_object();
    json_object_set_new(data, "service_name", json_string(cfg_agent_name));

    json_t *resp = daemon_call("service_heartbeat", data);
    json_decref(data);
    if (resp) json_decref(resp);
}

static json_t *ipc_recv(void) {
    json_t *data = json_object();
    json_object_set_new(data, "agent", json_string(cfg_agent_name));
    json_object_set_new(data, "ack_mode", json_string("manual"));
    json_object_set_new(data, "max_items", json_integer(MAX_RECV_BATCH));

    json_t *resp = daemon_call("ipc_recv", data);
    json_decref(data);
    return resp;
}

static void ipc_ack(json_t *msg_ids) {
    json_t *data = json_object();
    json_object_set_new(data, "agent", json_string(cfg_agent_name));
    json_object_set(data, "msg_ids", msg_ids);

    json_t *resp = daemon_call("ipc_ack", data);
    json_decref(data);
    if (resp) json_decref(resp);
}

static void ipc_send(const char *to, const char *conversation_id, json_t *payload) {
    json_t *data = json_object();
    json_object_set_new(data, "from", json_string(cfg_agent_name));
    json_object_set_new(data, "to", json_string(to));
    json_object_set(data, "payload", payload);
    if (conversation_id && conversation_id[0])
        json_object_set_new(data, "conversation_id", json_string(conversation_id));

    json_t *resp = daemon_call("ipc_send", data);
    json_decref(data);
    if (resp) json_decref(resp);
}

/* ── Response helper ── */
static void send_response(const char *to, const char *conv_id,
                          const char *event_type, const char *status_str,
                          json_t *result_data) {
    json_t *payload = json_object();
    json_object_set_new(payload, "event_type", json_string(event_type));
    json_object_set_new(payload, "status", json_string(status_str));
    if (result_data)
        json_object_set(payload, "data", result_data);
    ipc_send(to, conv_id, payload);
    json_decref(payload);
}

static void send_error(const char *to, const char *conv_id,
                       const char *event_type, json_t *errors) {
    json_t *payload = json_object();
    json_object_set_new(payload, "event_type", json_string(event_type));
    json_object_set_new(payload, "status", json_string("error"));
    if (errors)
        json_object_set(payload, "errors", errors);
    ipc_send(to, conv_id, payload);
    json_decref(payload);
}

/* ══════════════════════════════════════════════
 *  Message Handlers
 * ══════════════════════════════════════════════ */

static void handle_task_create(const char *from, const char *conv_id, json_t *msg_data) {
    json_t *errs = validate_task_create(msg_data, &g_task_store);
    if (errs) {
        tm_log("WARN", "TASK_CREATE rejected from %s", from);
        send_error(from, conv_id, "TASK_REJECTED", errs);
        json_decref(errs);
        return;
    }

    Task t;
    memset(&t, 0, sizeof(t));
    t.active = true;

    const char *v;
    if ((v = json_string_value(json_object_get(msg_data, "task_id"))))
        snprintf(t.task_id, sizeof(t.task_id), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "title"))))
        snprintf(t.title, sizeof(t.title), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "owner"))))
        snprintf(t.owner, sizeof(t.owner), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "priority"))))
        snprintf(t.priority, sizeof(t.priority), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "spec_id"))))
        snprintf(t.spec_id, sizeof(t.spec_id), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "group"))))
        snprintf(t.group, sizeof(t.group), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "description"))))
        snprintf(t.description, sizeof(t.description), "%s", v);
    if ((v = json_string_value(json_object_get(msg_data, "deadline"))))
        snprintf(t.deadline, sizeof(t.deadline), "%s", v);

    /* depends_on */
    json_t *deps = json_object_get(msg_data, "depends_on");
    if (json_is_array(deps)) {
        int n = (int)json_array_size(deps);
        if (n > TM_MAX_DEPS) n = TM_MAX_DEPS;
        for (int i = 0; i < n; i++) {
            const char *d = json_string_value(json_array_get(deps, i));
            if (d) snprintf(t.depends_on[i], TM_MAX_ID_LEN, "%s", d);
        }
        t.depends_count = n;
    }

    /* tags */
    json_t *tags = json_object_get(msg_data, "tags");
    if (json_is_array(tags)) {
        int n = (int)json_array_size(tags);
        if (n > TM_MAX_TAGS) n = TM_MAX_TAGS;
        for (int i = 0; i < n; i++) {
            const char *tg = json_string_value(json_array_get(tags, i));
            if (tg) snprintf(t.tags[i], 64, "%s", tg);
        }
        t.tags_count = n;
    }

    int rc = task_store_create(&g_task_store, &t);
    if (rc == 0) {
        tm_log("INFO", "TASK_CREATED: %s (owner=%s)", t.task_id, t.owner);
        json_t *result = task_to_json(&t);
        send_response(from, conv_id, "TASK_CREATED", "ok", result);
        json_decref(result);
    } else {
        tm_log("ERROR", "task_store_create failed: %d", rc);
        json_t *e = json_array();
        json_array_append_new(e, json_string("internal store error"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
    }
}

static void handle_task_update(const char *from, const char *conv_id, json_t *msg_data) {
    json_t *errs = validate_task_update(msg_data, &g_task_store);
    if (errs) {
        tm_log("WARN", "TASK_UPDATE rejected from %s", from);
        send_error(from, conv_id, "TASK_REJECTED", errs);
        json_decref(errs);
        return;
    }

    const char *task_id = json_string_value(json_object_get(msg_data, "task_id"));
    int rc = task_store_update(&g_task_store, task_id, msg_data);
    if (rc == 0) {
        tm_log("INFO", "TASK_UPDATED: %s", task_id);
        Task *t = task_store_get(&g_task_store, task_id);
        json_t *result = t ? task_to_json(t) : json_object();
        send_response(from, conv_id, "TASK_UPDATED", "ok", result);
        json_decref(result);
    } else {
        tm_log("ERROR", "task_store_update failed: %d", rc);
        json_t *e = json_array();
        char buf[128];
        snprintf(buf, sizeof(buf), "update failed (rc=%d)", rc);
        json_array_append_new(e, json_string(buf));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
    }
}

static void handle_task_query(const char *from, const char *conv_id, json_t *msg_data) {
    json_t *results = task_store_query(&g_task_store, msg_data ? msg_data : json_object());
    json_t *resp_data = json_object();
    json_object_set_new(resp_data, "tasks", results);
    json_object_set_new(resp_data, "count", json_integer((int)json_array_size(results)));
    send_response(from, conv_id, "TASK_QUERY_RESULT", "ok", resp_data);
    json_decref(resp_data);
}

static void handle_task_delete(const char *from, const char *conv_id, json_t *msg_data) {
    const char *task_id = json_string_value(json_object_get(msg_data, "task_id"));
    if (!task_id || !task_id[0]) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("missing task_id"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
        return;
    }

    int rc = task_store_delete(&g_task_store, task_id);
    if (rc == 0) {
        tm_log("INFO", "TASK_DELETED: %s", task_id);
        send_response(from, conv_id, "TASK_DELETED", "ok", NULL);
    } else {
        json_t *e = json_array();
        json_array_append_new(e, json_string("task not found"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
    }
}

static void handle_spec_create(const char *from, const char *conv_id, json_t *msg_data) {
    const char *spec_id = json_string_value(json_object_get(msg_data, "spec_id"));
    const char *title   = json_string_value(json_object_get(msg_data, "title"));
    const char *group   = json_string_value(json_object_get(msg_data, "group"));
    const char *owner   = json_string_value(json_object_get(msg_data, "owner"));

    if (!spec_id || !title || !group || !owner ||
        !spec_id[0] || !title[0] || !group[0] || !owner[0]) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("missing required fields: spec_id, title, group, owner"));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
        return;
    }

    int rc = spec_store_create(&g_spec_store, spec_id, title, group, owner);
    if (rc == 0) {
        tm_log("INFO", "SPEC_CREATED: %s (group=%s)", spec_id, group);
        SpecRecord *r = spec_store_get(&g_spec_store, spec_id);
        json_t *result = json_object();
        json_object_set_new(result, "spec_id", json_string(spec_id));
        json_object_set_new(result, "stage", json_string(r ? spec_stage_str(r->stage) : "S1_alignment"));
        send_response(from, conv_id, "SPEC_CREATED", "ok", result);
        json_decref(result);
    } else {
        tm_log("ERROR", "spec_store_create failed: %d", rc);
        json_t *e = json_array();
        json_array_append_new(e, json_string(rc == -1 ? "duplicate spec_id" : "store full"));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
    }
}

static void handle_spec_progress(const char *from, const char *conv_id, json_t *msg_data) {
    const char *spec_id = json_string_value(json_object_get(msg_data, "spec_id"));
    const char *stage   = json_string_value(json_object_get(msg_data, "stage"));
    bool force          = json_is_true(json_object_get(msg_data, "force"));

    if (!spec_id || !stage || !spec_id[0] || !stage[0]) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("missing required fields: spec_id, stage"));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
        return;
    }

    int rc = spec_store_advance(&g_spec_store, spec_id, stage, force);
    if (rc == 0) {
        tm_log("INFO", "SPEC_ADVANCED: %s -> %s", spec_id, stage);
        json_t *result = json_object();
        json_object_set_new(result, "spec_id", json_string(spec_id));
        json_object_set_new(result, "stage", json_string(stage));
        send_response(from, conv_id, "SPEC_ADVANCED", "ok", result);
        json_decref(result);
    } else {
        const char *reason = "unknown";
        if (rc == -1) reason = "spec not found";
        else if (rc == -3) reason = "cannot go backward";
        else if (rc == -4) reason = "cannot skip stages";
        tm_log("WARN", "SPEC_PROGRESS rejected: %s -> %s (%s)", spec_id, stage, reason);
        json_t *e = json_array();
        json_array_append_new(e, json_string(reason));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
    }
}

static void handle_spec_query(const char *from, const char *conv_id, json_t *msg_data) {
    json_t *results = spec_store_query(&g_spec_store, msg_data ? msg_data : json_object());
    json_t *resp_data = json_object();
    json_object_set_new(resp_data, "specs", results);
    json_object_set_new(resp_data, "count", json_integer((int)json_array_size(results)));
    send_response(from, conv_id, "SPEC_QUERY_RESULT", "ok", resp_data);
    json_decref(resp_data);
}

static void handle_health(const char *from, const char *conv_id) {
    json_t *result = json_object();
    json_object_set_new(result, "service", json_string(cfg_agent_name));
    json_object_set_new(result, "status", json_string("healthy"));
    json_object_set_new(result, "tasks_count", json_integer(g_task_store.count));
    json_object_set_new(result, "specs_count", json_integer(g_spec_store.count));
    json_t *loop = json_object();
    json_object_set_new(loop, "uptime_s", json_integer((json_int_t)(time(NULL) - g_started_at)));
    json_object_set_new(loop, "loops", json_integer((json_int_t)g_metrics.loops));
    json_object_set_new(loop, "notify_wakeups", json_integer((json_int_t)g_metrics.notify_wakeups));
    json_object_set_new(loop, "timeouts", json_integer((json_int_t)g_metrics.timeouts));
    json_object_set_new(loop, "notify_disconnects", json_integer((json_int_t)g_metrics.notify_disconnects));
    json_object_set_new(loop, "notify_reconnect_attempts", json_integer((json_int_t)g_metrics.notify_reconnect_attempts));
    json_object_set_new(loop, "notify_reconnect_success", json_integer((json_int_t)g_metrics.notify_reconnect_success));
    json_object_set_new(loop, "ipc_recv_calls", json_integer((json_int_t)g_metrics.ipc_recv_calls));
    json_object_set_new(loop, "ipc_recv_failures", json_integer((json_int_t)g_metrics.ipc_recv_failures));
    json_object_set_new(loop, "ipc_batches_processed", json_integer((json_int_t)g_metrics.ipc_batches_processed));
    json_object_set_new(loop, "ipc_messages_processed", json_integer((json_int_t)g_metrics.ipc_messages_processed));
    json_object_set_new(loop, "ipc_ack_batches", json_integer((json_int_t)g_metrics.ipc_ack_batches));
    json_object_set_new(result, "event_loop", loop);
    char ts[32]; now_iso(ts, sizeof(ts));
    json_object_set_new(result, "timestamp", json_string(ts));
    send_response(from, conv_id, "HEALTH_RESPONSE", "ok", result);
    json_decref(result);
}

static void handle_ping(const char *from, const char *conv_id) {
    json_t *result = json_object();
    json_object_set_new(result, "pong", json_true());
    send_response(from, conv_id, "PONG", "ok", result);
    json_decref(result);
}

/* Forward declaration for batch processor. */
static void route_message(json_t *msg);

/* Process one ipc_recv response and ack in batch to reduce IPC overhead. */
static int process_recv_batch(json_t *resp) {
    json_t *messages = json_object_get(resp, "messages");
    if (!json_is_array(messages)) return 0;

    size_t n = json_array_size(messages);
    if (n == 0) return 0;

    int processed = 0;
    json_t *ack_ids = json_array();
    for (size_t i = 0; i < n && !g_shutdown; i++) {
        json_t *msg = json_array_get(messages, i);
        if (!json_is_object(msg)) continue;

        const char *msg_id = json_string_value(json_object_get(msg, "msg_id"));
        route_message(msg);
        processed++;

        if (msg_id && msg_id[0])
            json_array_append_new(ack_ids, json_string(msg_id));
    }

    if (json_array_size(ack_ids) > 0) {
        ipc_ack(ack_ids);
        g_metrics.ipc_ack_batches++;
    }
    json_decref(ack_ids);
    g_metrics.ipc_batches_processed++;
    g_metrics.ipc_messages_processed += (unsigned long)processed;
    return processed;
}

/* Pull and process up to max_rounds batches. Returns -1 only when the first
 * recv fails (transport level error). */
static int ipc_fetch_and_process(int max_rounds) {
    int total = 0;
    if (max_rounds <= 0) max_rounds = 1;

    for (int round = 0; round < max_rounds && !g_shutdown; round++) {
        g_metrics.ipc_recv_calls++;
        json_t *resp = ipc_recv();
        if (!resp) {
            g_metrics.ipc_recv_failures++;
            if (total == 0) return -1;
            break;
        }

        int count = process_recv_batch(resp);
        json_decref(resp);
        total += count;

        if (count < MAX_RECV_BATCH) break;
    }
    return total;
}

static int min_non_negative(int a, int b) {
    if (a < 0) return b;
    if (b < 0) return a;
    return (a < b) ? a : b;
}

static int compute_loop_timeout_s(int nfd, time_t next_notify_retry_ts) {
    time_t now = time(NULL);
    int timeout_s = SCHEDULER_INTERVAL_S;

    int hb_due = HEARTBEAT_INTERVAL - (int)(now - g_last_heartbeat);
    if (hb_due < 0) hb_due = 0;
    timeout_s = min_non_negative(timeout_s, hb_due);

    if (nfd < 0) {
        timeout_s = min_non_negative(timeout_s, DISCONNECTED_POLL_INTERVAL_S);
        int reconnect_due = (int)(next_notify_retry_ts - now);
        if (reconnect_due < 0) reconnect_due = 0;
        timeout_s = min_non_negative(timeout_s, reconnect_due);
    }

    if (timeout_s < 0) timeout_s = 0;
    return timeout_s;
}

static void maybe_log_metrics(void) {
    time_t now = time(NULL);
    if (now - g_last_metrics_log < METRICS_LOG_INTERVAL_S) return;
    g_last_metrics_log = now;

    unsigned long uptime = (unsigned long)(now - g_started_at);
    tm_log("INFO",
           "metrics uptime_s=%lu loops=%lu wakeups=%lu timeouts=%lu "
           "notify_disconnects=%lu reconnect_attempts=%lu reconnect_success=%lu "
           "ipc_recv_calls=%lu ipc_recv_failures=%lu batches=%lu msgs=%lu ack_batches=%lu",
           uptime, g_metrics.loops, g_metrics.notify_wakeups, g_metrics.timeouts,
           g_metrics.notify_disconnects, g_metrics.notify_reconnect_attempts,
           g_metrics.notify_reconnect_success, g_metrics.ipc_recv_calls,
           g_metrics.ipc_recv_failures, g_metrics.ipc_batches_processed,
           g_metrics.ipc_messages_processed, g_metrics.ipc_ack_batches);
}

/* ── Message Router ── */
static void route_message(json_t *msg) {
    /* msg structure from daemon ipc_recv:
     *   { "msg_id": "...", "from": "...", "payload": {...}, "conversation_id": "..." }
     */
    const char *msg_id  = json_string_value(json_object_get(msg, "msg_id"));
    const char *from    = json_string_value(json_object_get(msg, "from"));
    const char *conv_id = json_string_value(json_object_get(msg, "conversation_id"));
    json_t *payload     = json_object_get(msg, "payload");

    if (!from) from = "unknown";
    if (!payload) payload = json_object();

    const char *event_type = json_string_value(json_object_get(payload, "event_type"));
    if (!event_type) event_type = "";

    json_t *data = json_object_get(payload, "data");
    if (!data) data = payload; /* fallback: use payload itself as data */

    tm_log("INFO", "recv [%s] from=%s event=%s", msg_id ? msg_id : "?", from, event_type);

    if (strcmp(event_type, "TASK_CREATE") == 0)
        handle_task_create(from, conv_id, data);
    else if (strcmp(event_type, "TASK_UPDATE") == 0)
        handle_task_update(from, conv_id, data);
    else if (strcmp(event_type, "TASK_QUERY") == 0)
        handle_task_query(from, conv_id, data);
    else if (strcmp(event_type, "TASK_DELETE") == 0)
        handle_task_delete(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_CREATE") == 0)
        handle_spec_create(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_PROGRESS") == 0)
        handle_spec_progress(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_QUERY") == 0)
        handle_spec_query(from, conv_id, data);
    else if (strcmp(event_type, "HEALTH") == 0)
        handle_health(from, conv_id);
    else if (strcmp(event_type, "PING") == 0)
        handle_ping(from, conv_id);
    else {
        tm_log("WARN", "unknown event_type: '%s' from %s", event_type, from);
        json_t *e = json_array();
        char buf[256];
        snprintf(buf, sizeof(buf), "unknown event_type: %s", event_type);
        json_array_append_new(e, json_string(buf));
        send_error(from, conv_id, "UNKNOWN_EVENT", e);
        json_decref(e);
    }

}

/* ══════════════════════════════════════════════
 *  Scheduler — deadline / stale checks
 * ══════════════════════════════════════════════ */

static time_t parse_iso_time(const char *iso) {
    if (!iso || !iso[0]) return 0;
    struct tm tm;
    memset(&tm, 0, sizeof(tm));
    /* try YYYY-MM-DDTHH:MM:SSZ */
    if (strptime(iso, "%Y-%m-%dT%H:%M:%S", &tm))
        return timegm(&tm);
    /* try YYYY-MM-DD */
    if (strptime(iso, "%Y-%m-%d", &tm))
        return timegm(&tm);
    return 0;
}

static void scheduler_tick(void) {
    time_t now = time(NULL);

    /* Deadline reminders */
    if (now - g_last_deadline_check >= cfg_deadline_interval) {
        g_last_deadline_check = now;
        pthread_mutex_lock(&g_task_store.mu);
        for (int i = 0; i < g_task_store.count; i++) {
            Task *t = &g_task_store.tasks[i];
            if (!t->active) continue;
            if (t->status == TS_COMPLETED || t->status == TS_CANCELLED || t->status == TS_ARCHIVED)
                continue;
            if (!t->deadline[0]) continue;

            time_t dl = parse_iso_time(t->deadline);
            if (dl == 0) continue;
            double hours_left = difftime(dl, now) / 3600.0;
            if (hours_left > 0 && hours_left < cfg_deadline_warning_h) {
                tm_log("INFO", "DEADLINE_REMINDER: %s (%.1fh left) -> %s",
                       t->task_id, hours_left, t->owner);
                json_t *alert = json_object();
                json_object_set_new(alert, "event_type", json_string("TASK_REMINDER"));
                json_object_set_new(alert, "task_id", json_string(t->task_id));
                json_object_set_new(alert, "title", json_string(t->title));
                json_object_set_new(alert, "hours_left", json_real(hours_left));
                if (t->owner[0])
                    ipc_send(t->owner, NULL, alert);
                json_decref(alert);
            }
        }
        pthread_mutex_unlock(&g_task_store.mu);
    }

    /* Stale tasks */
    if (now - g_last_stale_task_check >= cfg_stale_task_interval) {
        g_last_stale_task_check = now;
        pthread_mutex_lock(&g_task_store.mu);
        for (int i = 0; i < g_task_store.count; i++) {
            Task *t = &g_task_store.tasks[i];
            if (!t->active) continue;
            if (t->status != TS_IN_PROGRESS) continue;

            time_t updated = parse_iso_time(t->updated_at);
            if (updated == 0) continue;
            double hours_stale = difftime(now, updated) / 3600.0;
            if (hours_stale > cfg_stale_task_h) {
                tm_log("INFO", "STALE_TASK: %s (%.1fh stale) group=%s",
                       t->task_id, hours_stale, t->group);
                json_t *alert = json_object();
                json_object_set_new(alert, "event_type", json_string("TASK_STALE_ALERT"));
                json_object_set_new(alert, "task_id", json_string(t->task_id));
                json_object_set_new(alert, "title", json_string(t->title));
                json_object_set_new(alert, "owner", json_string(t->owner));
                json_object_set_new(alert, "hours_stale", json_real(hours_stale));
                /* send to group PMO */
                char pmo[128];
                snprintf(pmo, sizeof(pmo), "agent_%s_pmo",
                         t->group[0] ? t->group : "system");
                ipc_send(pmo, NULL, alert);
                json_decref(alert);
            }
        }
        pthread_mutex_unlock(&g_task_store.mu);
    }

    /* Stale specs */
    if (now - g_last_stale_spec_check >= cfg_stale_spec_interval) {
        g_last_stale_spec_check = now;
        pthread_mutex_lock(&g_spec_store.mu);
        for (int i = 0; i < g_spec_store.count; i++) {
            SpecRecord *r = &g_spec_store.specs[i];
            if (!r->active) continue;
            if (r->stage == SS_S8_COMPLETE || r->stage == SS_ARCHIVED) continue;

            time_t updated = parse_iso_time(r->updated_at);
            if (updated == 0) continue;
            double hours_stale = difftime(now, updated) / 3600.0;
            if (hours_stale > cfg_stale_spec_h) {
                tm_log("INFO", "STALE_SPEC: %s stage=%s (%.1fh stale)",
                       r->spec_id, spec_stage_str(r->stage), hours_stale);
                json_t *alert = json_object();
                json_object_set_new(alert, "event_type", json_string("SPEC_STALE_ALERT"));
                json_object_set_new(alert, "spec_id", json_string(r->spec_id));
                json_object_set_new(alert, "stage", json_string(spec_stage_str(r->stage)));
                json_object_set_new(alert, "hours_stale", json_real(hours_stale));
                if (r->owner[0])
                    ipc_send(r->owner, NULL, alert);
                json_decref(alert);
            }
        }
        pthread_mutex_unlock(&g_spec_store.mu);
    }
}

/* ══════════════════════════════════════════════
 *  Config loader (simple YAML-like key extraction from jansson)
 * ══════════════════════════════════════════════ */

static void load_config(const char *config_path) {
    if (!config_path) return;

    /* We read the YAML config line-by-line and extract known keys.
     * This avoids a libyaml dependency; the config is simple flat key: value. */
    FILE *f = fopen(config_path, "r");
    if (!f) return;

    char line[512];
    while (fgets(line, sizeof(line), f)) {
        /* trim leading whitespace */
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;

        char key[128], val[384];
        if (sscanf(p, "%127[^:]: %383[^\n]", key, val) == 2) {
            /* trim trailing whitespace from val */
            char *e = val + strlen(val) - 1;
            while (e >= val && (*e == ' ' || *e == '\n' || *e == '\r')) *e-- = '\0';

            if (strcmp(key, "agent_name") == 0)
                snprintf(cfg_agent_name, sizeof(cfg_agent_name), "%s", val);
            else if (strcmp(key, "socket_path") == 0)
                snprintf(cfg_socket_path, sizeof(cfg_socket_path), "%s", val);
            else if (strcmp(key, "data_dir") == 0)
                snprintf(cfg_data_dir, sizeof(cfg_data_dir), "%s", val);
            else if (strcmp(key, "log_file") == 0)
                snprintf(cfg_log_file, sizeof(cfg_log_file), "%s", val);
            else if (strcmp(key, "deadline_reminder_interval_s") == 0)
                cfg_deadline_interval = atoi(val);
            else if (strcmp(key, "stale_task_interval_s") == 0)
                cfg_stale_task_interval = atoi(val);
            else if (strcmp(key, "stale_spec_interval_s") == 0)
                cfg_stale_spec_interval = atoi(val);
            else if (strcmp(key, "deadline_warning_hours") == 0)
                cfg_deadline_warning_h = atoi(val);
            else if (strcmp(key, "stale_task_hours") == 0)
                cfg_stale_task_h = atoi(val);
            else if (strcmp(key, "stale_spec_hours") == 0)
                cfg_stale_spec_h = atoi(val);
        }
    }
    fclose(f);
}

/* ══════════════════════════════════════════════
 *  Main
 * ══════════════════════════════════════════════ */

int main(int argc, char **argv) {
    /* Config path: argv[1] or default */
    const char *config_path = "/brain/infrastructure/service/task-manager/config/task_manager.yaml";
    if (argc > 1) config_path = argv[1];

    load_config(config_path);

    /* Ensure data dir exists */
    mkdir(cfg_data_dir, 0755);

    /* Open log */
    g_logfile = fopen(cfg_log_file, "a");
    if (!g_logfile) g_logfile = stderr;
    g_started_at = time(NULL);
    g_last_metrics_log = g_started_at;

    tm_log("INFO", "=== service-task_manager starting ===");
    tm_log("INFO", "config: socket=%s agent=%s data=%s", cfg_socket_path, cfg_agent_name, cfg_data_dir);

    /* Signal handlers */
    signal(SIGTERM, on_signal);
    signal(SIGINT,  on_signal);
    signal(SIGPIPE, SIG_IGN);

    /* Init stores */
    task_store_init(&g_task_store, cfg_data_dir);
    spec_store_init(&g_spec_store, cfg_data_dir);

    int tc = task_store_load(&g_task_store);
    int sc = spec_store_load(&g_spec_store);
    tm_log("INFO", "loaded %d tasks, %d specs", tc < 0 ? 0 : tc, sc < 0 ? 0 : sc);

    /* Register with daemon */
    int retry = 0;
    while (!g_shutdown && retry < 10) {
        if (ipc_register()) {
            tm_log("INFO", "registered as %s", cfg_agent_name);
            break;
        }
        retry++;
        tm_log("WARN", "register failed, retry %d/10...", retry);
        usleep(1000000); /* 1s */
    }
    if (retry >= 10 && !g_shutdown) {
        tm_log("ERROR", "failed to register after 10 retries, exiting");
        return 1;
    }

    /* Init scheduler timers */
    time_t now = time(NULL);
    g_last_deadline_check   = now;
    g_last_stale_task_check = now;
    g_last_stale_spec_check = now;

    tm_log("INFO", "entering main loop (notify-based)");

    /* Connect to notify socket for push-based wake-up */
    int nfd = notify_connect();
    if (nfd < 0) {
        tm_log("WARN", "notify socket unavailable, will retry periodically");
    }

    /* Drain any messages queued before notify connected */
    if (ipc_fetch_and_process(IPC_DRAIN_MAX_ROUNDS) < 0)
        usleep(IPC_ERROR_BACKOFF_US);

    int notify_retry_backoff_s = NOTIFY_RECONNECT_BASE_S;
    time_t next_notify_retry_ts = time(NULL);

    /* ── Main Loop ── */
    while (!g_shutdown) {
        g_metrics.loops++;
        /* 1. Wait for notify or timeout (for scheduler ticks) */
        int wait_s = compute_loop_timeout_s(nfd, next_notify_retry_ts);
        int ready = notify_wait(nfd, wait_s);

        if (ready > 0) {
            g_metrics.notify_wakeups++;
            /* Notify received — drain socket, then fetch messages */
            if (notify_drain(nfd) < 0) {
                tm_log("WARN", "notify socket disconnected, switch to poll mode");
                g_metrics.notify_disconnects++;
                if (nfd >= 0) close(nfd);
                nfd = -1;
            } else if (ipc_fetch_and_process(IPC_DRAIN_MAX_ROUNDS) < 0) {
                tm_log("WARN", "ipc_recv failed after notify wake-up");
                usleep(IPC_ERROR_BACKOFF_US);
            }
        } else if (ready < 0) {
            /* select error — reconnect notify socket */
            tm_log("WARN", "notify select error: %s", strerror(errno));
            if (nfd >= 0) close(nfd);
            nfd = -1;
        } else if (nfd >= 0) {
            g_metrics.timeouts++;
            /* Safety pull in case notify signal is missed. */
            if (ipc_fetch_and_process(1) < 0) {
                tm_log("WARN", "ipc_recv failed on timeout safety pull");
                usleep(IPC_ERROR_BACKOFF_US);
            }
        }

        if (nfd < 0) {
            if (ipc_fetch_and_process(1) < 0)
                usleep(IPC_ERROR_BACKOFF_US);

            time_t now_retry = time(NULL);
            if (now_retry >= next_notify_retry_ts) {
                g_metrics.notify_reconnect_attempts++;
                int new_fd = notify_connect();
                if (new_fd >= 0) {
                    nfd = new_fd;
                    g_metrics.notify_reconnect_success++;
                    notify_retry_backoff_s = NOTIFY_RECONNECT_BASE_S;
                    next_notify_retry_ts = now_retry;
                    tm_log("INFO", "notify reconnected");
                } else {
                    tm_log("WARN", "notify reconnect failed, retry in %ds", notify_retry_backoff_s);
                    next_notify_retry_ts = now_retry + notify_retry_backoff_s;
                    if (notify_retry_backoff_s < NOTIFY_RECONNECT_MAX_S) {
                        notify_retry_backoff_s *= 2;
                        if (notify_retry_backoff_s > NOTIFY_RECONNECT_MAX_S)
                            notify_retry_backoff_s = NOTIFY_RECONNECT_MAX_S;
                    }
                }
            }
        }

        /* 2. Scheduler tick */
        scheduler_tick();

        /* 3. Service heartbeat */
        time_t now_hb = time(NULL);
        if (now_hb - g_last_heartbeat >= HEARTBEAT_INTERVAL) {
            ipc_heartbeat();
            g_last_heartbeat = now_hb;
        }

        maybe_log_metrics();
    }

    if (nfd >= 0) close(nfd);

    /* ── Graceful shutdown ── */
    tm_log("INFO", "shutting down...");
    task_store_flush(&g_task_store);
    spec_store_flush(&g_spec_store);
    tm_log("INFO", "data flushed, exiting");

    if (g_logfile && g_logfile != stderr)
        fclose(g_logfile);

    return 0;
}
