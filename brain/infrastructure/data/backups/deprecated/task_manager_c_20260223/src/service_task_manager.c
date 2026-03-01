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
 *   TASK_STATS, TASK_PIPELINE_CHECK
 *   SPEC_CREATE, SPEC_PROGRESS, SPEC_QUERY
 *   PROJECT_DEPENDENCY_SET, PROJECT_DEPENDENCY_QUERY
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
#include <netinet/in.h>
#include <arpa/inet.h>
#include <stdarg.h>

/* ── Config ── */
#define DEFAULT_SOCKET       "/tmp/brain_ipc.sock"
#define DEFAULT_NOTIFY_SOCK  "/tmp/brain_ipc_notify.sock"
#define DEFAULT_AGENT_NAME   "service-task_manager"
#define DEFAULT_DATA_DIR     "/brain/infrastructure/service/task_manager/data"
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
static int cfg_health_port         = 8091;
static bool cfg_check_owner_online = true;

static char cfg_socket_path[512]   = DEFAULT_SOCKET;
static char cfg_agent_name[128]    = DEFAULT_AGENT_NAME;
static char cfg_data_dir[512]      = DEFAULT_DATA_DIR;
static char cfg_log_file[512]      = DEFAULT_LOG_FILE;

/* ── Health server ── */
static int g_health_fd = -1;
static pthread_t g_health_thread;
static bool g_health_thread_started = false;
static pthread_mutex_t g_project_dep_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t g_dispatch_guard_mu = PTHREAD_MUTEX_INITIALIZER;

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

static bool is_true_like(const char *val) {
    if (!val) return false;
    return strcmp(val, "true") == 0 || strcmp(val, "True") == 0 ||
           strcmp(val, "TRUE") == 0 || strcmp(val, "1") == 0 ||
           strcmp(val, "yes") == 0 || strcmp(val, "on") == 0;
}

/* Return 1: online, 0: exists but offline/not found, -1: lookup error */
static int owner_online_state(const char *owner) {
    if (!owner || !owner[0]) return 0;

    json_t *req = json_object();
    json_object_set_new(req, "include_offline", json_true());
    json_t *resp = daemon_call("agent_list", req);
    json_decref(req);
    if (!resp) return -1;

    json_t *agents = json_object_get(resp, "agents");
    if (!json_is_array(agents)) {
        json_decref(resp);
        return -1;
    }

    size_t n = json_array_size(agents);
    for (size_t i = 0; i < n; i++) {
        json_t *a = json_array_get(agents, i);
        if (!json_is_object(a)) continue;
        const char *name = json_string_value(json_object_get(a, "name"));
        if (!name || strcmp(name, owner) != 0) continue;
        int online = json_is_true(json_object_get(a, "online")) ? 1 : 0;
        json_decref(resp);
        return online;
    }

    json_decref(resp);
    return 0;
}

static void maybe_trigger_task_knowledge_sync(const Task *t) {
    if (!t || t->status != TS_COMPLETED) return;

    bool has_tag = false;
    for (int i = 0; i < t->tags_count; i++) {
        if (strcmp(t->tags[i], "knowledge-sync") == 0) {
            has_tag = true;
            break;
        }
    }
    if (!has_tag) return;

    char target[128];
    snprintf(target, sizeof(target), "agent_%s_pmo", t->group[0] ? t->group : "system");

    json_t *payload = json_object();
    json_object_set_new(payload, "event_type", json_string("KNOWLEDGE_SYNC_REQUEST"));
    json_t *data = json_object();
    json_object_set_new(data, "source", json_string("task_manager"));
    json_object_set_new(data, "kind", json_string("task_completed"));
    json_object_set_new(data, "task_id", json_string(t->task_id));
    json_object_set_new(data, "title", json_string(t->title));
    json_object_set_new(data, "group", json_string(t->group));
    json_object_set_new(data, "spec_id", json_string(t->spec_id));
    json_object_set_new(data, "owner", json_string(t->owner));
    json_object_set_new(data, "reason", json_string("task completed with knowledge-sync tag"));
    json_object_set(payload, "data", data);
    json_decref(data);

    ipc_send(target, NULL, payload);
    json_decref(payload);
    tm_log("INFO", "KNOWLEDGE_SYNC_REQUEST sent for task %s -> %s", t->task_id, target);
}

static void maybe_trigger_spec_knowledge_sync(const SpecRecord *r) {
    if (!r || r->stage != SS_ARCHIVED) return;

    const char *target = r->owner[0] ? r->owner : "agent_system_pmo";
    json_t *payload = json_object();
    json_object_set_new(payload, "event_type", json_string("KNOWLEDGE_SYNC_REQUEST"));
    json_t *data = json_object();
    json_object_set_new(data, "source", json_string("task_manager"));
    json_object_set_new(data, "kind", json_string("spec_archived"));
    json_object_set_new(data, "spec_id", json_string(r->spec_id));
    json_object_set_new(data, "title", json_string(r->title));
    json_object_set_new(data, "group", json_string(r->group));
    json_object_set_new(data, "owner", json_string(r->owner));
    json_object_set_new(data, "reason", json_string("spec archived"));
    json_object_set(payload, "data", data);
    json_decref(data);

    ipc_send(target, NULL, payload);
    json_decref(payload);
    tm_log("INFO", "KNOWLEDGE_SYNC_REQUEST sent for spec %s -> %s", r->spec_id, target);
}

static char *build_health_json_body(void) {
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
    json_object_set_new(loop, "ipc_recv_calls", json_integer((json_int_t)g_metrics.ipc_recv_calls));
    json_object_set_new(loop, "ipc_recv_failures", json_integer((json_int_t)g_metrics.ipc_recv_failures));
    json_object_set_new(result, "event_loop", loop);
    char ts[32];
    now_iso(ts, sizeof(ts));
    json_object_set_new(result, "timestamp", json_string(ts));

    char *body = json_dumps(result, JSON_COMPACT);
    json_decref(result);
    return body;
}

static void *health_server_thread(void *unused) {
    (void)unused;
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        tm_log("WARN", "health socket create failed: %s", strerror(errno));
        return NULL;
    }

    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)cfg_health_port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        tm_log("WARN", "health bind 127.0.0.1:%d failed: %s", cfg_health_port, strerror(errno));
        close(fd);
        return NULL;
    }
    if (listen(fd, 16) != 0) {
        tm_log("WARN", "health listen failed: %s", strerror(errno));
        close(fd);
        return NULL;
    }

    g_health_fd = fd;
    tm_log("INFO", "health endpoint listening on 127.0.0.1:%d", cfg_health_port);

    while (!g_shutdown) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(fd, &rfds);
        struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };
        int rc = select(fd + 1, &rfds, NULL, NULL, &tv);
        if (rc <= 0) continue;

        int cfd = accept(fd, NULL, NULL);
        if (cfd < 0) continue;

        char req[512];
        ssize_t n = read(cfd, req, sizeof(req) - 1);
        if (n < 0) n = 0;
        req[n] = '\0';

        if (strncmp(req, "GET /health", 11) == 0) {
            char *body = build_health_json_body();
            if (!body) body = strdup("{\"status\":\"error\"}");
            char header[256];
            int hlen = snprintf(header, sizeof(header),
                                "HTTP/1.1 200 OK\r\n"
                                "Content-Type: application/json\r\n"
                                "Content-Length: %zu\r\n"
                                "Connection: close\r\n\r\n",
                                strlen(body));
            write(cfd, header, (size_t)hlen);
            write(cfd, body, strlen(body));
            free(body);
        } else {
            static const char *not_found =
                "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
            write(cfd, not_found, strlen(not_found));
        }
        close(cfd);
    }

    close(fd);
    g_health_fd = -1;
    return NULL;
}

static void start_health_server(void) {
    if (cfg_health_port <= 0) return;
    if (pthread_create(&g_health_thread, NULL, health_server_thread, NULL) == 0) {
        g_health_thread_started = true;
    } else {
        tm_log("WARN", "failed to start health endpoint thread");
    }
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

static bool compose_data_path(char *buf, size_t len, const char *filename) {
    if (!buf || len == 0 || !filename || !filename[0]) return false;
    size_t dlen = strlen(cfg_data_dir);
    size_t flen = strlen(filename);
    bool has_trailing_slash = (dlen > 0 && cfg_data_dir[dlen - 1] == '/');
    size_t need = dlen + (has_trailing_slash ? 0 : 1) + flen + 1;
    if (need > len) return false;

    memcpy(buf, cfg_data_dir, dlen);
    size_t pos = dlen;
    if (!has_trailing_slash) buf[pos++] = '/';
    memcpy(buf + pos, filename, flen);
    buf[pos + flen] = '\0';
    return true;
}

static int count_tasks_for_project(const char *project_id) {
    if (!project_id || !project_id[0]) return 0;
    int count = 0;
    pthread_mutex_lock(&g_task_store.mu);
    for (int i = 0; i < g_task_store.count; i++) {
        Task *t = &g_task_store.tasks[i];
        if (!t->active) continue;
        if (strcmp(t->spec_id, project_id) == 0) count++;
    }
    pthread_mutex_unlock(&g_task_store.mu);
    return count;
}

static bool spec_exists(const char *project_id) {
    if (!project_id || !project_id[0]) return false;
    SpecRecord *r = spec_store_get(&g_spec_store, project_id);
    return r && r->active;
}

static bool dispatch_guard_store_path(char *buf, size_t len) {
    return compose_data_path(buf, len, "project_dispatch_guard.json");
}

static json_t *dispatch_guard_load_root(void) {
    char path[512];
    if (!dispatch_guard_store_path(path, sizeof(path))) return json_object();

    json_error_t err;
    json_t *root = json_load_file(path, 0, &err);
    if (!root || !json_is_object(root)) {
        if (root) json_decref(root);
        root = json_object();
    }
    if (!json_is_object(json_object_get(root, "projects")))
        json_object_set_new(root, "projects", json_object());
    return root;
}

static int dispatch_guard_flush_root(json_t *root) {
    char path[512];
    char tmp[520];
    if (!dispatch_guard_store_path(path, sizeof(path))) return -1;
    if (snprintf(tmp, sizeof(tmp), "%s.tmp", path) >= (int)sizeof(tmp)) return -1;

    mkdir(cfg_data_dir, 0755);
    if (json_dump_file(root, tmp, JSON_INDENT(2) | JSON_ENSURE_ASCII) != 0) return -1;
    if (rename(tmp, path) != 0) {
        unlink(tmp);
        return -1;
    }
    return 0;
}

static json_t *dispatch_guard_get_record(json_t *root, const char *project_id, bool create) {
    if (!json_is_object(root) || !project_id || !project_id[0]) return NULL;
    json_t *projects = json_object_get(root, "projects");
    if (!json_is_object(projects)) return NULL;

    json_t *rec = json_object_get(projects, project_id);
    if (!rec && create) {
        rec = json_object();
        json_object_set_new(rec, "project_id", json_string(project_id));
        json_object_set_new(rec, "stats_checked_task_count", json_integer(-1));
        json_object_set_new(rec, "pipeline_checked_task_count", json_integer(-1));
        json_object_set_new(rec, "pipeline_valid", json_false());
        json_object_set_new(rec, "deps_set", json_false());
        json_object_set_new(projects, project_id, rec);
        rec = json_object_get(projects, project_id);
    }
    return (rec && json_is_object(rec)) ? rec : NULL;
}

static void dispatch_guard_set_updated(json_t *rec, const char *updated_by) {
    if (!json_is_object(rec)) return;
    char ts[32];
    now_iso(ts, sizeof(ts));
    json_object_set_new(rec, "updated_at", json_string(ts));
    json_object_set_new(rec, "updated_by", json_string((updated_by && updated_by[0]) ? updated_by : cfg_agent_name));
}

static void dispatch_guard_mark_stats(const char *project_id, int task_count, const char *updated_by) {
    if (!project_id || !project_id[0]) return;
    pthread_mutex_lock(&g_dispatch_guard_mu);
    json_t *root = dispatch_guard_load_root();
    json_t *rec = dispatch_guard_get_record(root, project_id, true);
    if (rec) {
        json_object_set_new(rec, "stats_checked_task_count", json_integer(task_count));
        dispatch_guard_set_updated(rec, updated_by);
        if (dispatch_guard_flush_root(root) != 0)
            tm_log("WARN", "dispatch guard flush failed (stats): %s", project_id);
    }
    json_decref(root);
    pthread_mutex_unlock(&g_dispatch_guard_mu);
}

static void dispatch_guard_mark_pipeline(const char *project_id, int task_count, bool valid, const char *updated_by) {
    if (!project_id || !project_id[0]) return;
    pthread_mutex_lock(&g_dispatch_guard_mu);
    json_t *root = dispatch_guard_load_root();
    json_t *rec = dispatch_guard_get_record(root, project_id, true);
    if (rec) {
        json_object_set_new(rec, "pipeline_checked_task_count", json_integer(task_count));
        json_object_set_new(rec, "pipeline_valid", valid ? json_true() : json_false());
        dispatch_guard_set_updated(rec, updated_by);
        if (dispatch_guard_flush_root(root) != 0)
            tm_log("WARN", "dispatch guard flush failed (pipeline): %s", project_id);
    }
    json_decref(root);
    pthread_mutex_unlock(&g_dispatch_guard_mu);
}

static void dispatch_guard_mark_dependencies(const char *project_id, const char *updated_by) {
    if (!project_id || !project_id[0]) return;
    pthread_mutex_lock(&g_dispatch_guard_mu);
    json_t *root = dispatch_guard_load_root();
    json_t *rec = dispatch_guard_get_record(root, project_id, true);
    if (rec) {
        json_object_set_new(rec, "deps_set", json_true());
        dispatch_guard_set_updated(rec, updated_by);
        if (dispatch_guard_flush_root(root) != 0)
            tm_log("WARN", "dispatch guard flush failed (deps): %s", project_id);
    }
    json_decref(root);
    pthread_mutex_unlock(&g_dispatch_guard_mu);
}

static json_t *dispatch_guard_missing_checks(const char *project_id, int task_count) {
    json_t *missing = json_array();
    if (!project_id || !project_id[0]) return missing;

    pthread_mutex_lock(&g_dispatch_guard_mu);
    json_t *root = dispatch_guard_load_root();
    json_t *rec = dispatch_guard_get_record(root, project_id, false);

    if (!rec) {
        json_array_append_new(missing, json_string("TASK_STATS"));
        json_array_append_new(missing, json_string("TASK_PIPELINE_CHECK"));
        json_array_append_new(missing, json_string("PROJECT_DEPENDENCY_SET"));
    } else {
        int stats_count = (int)json_integer_value(json_object_get(rec, "stats_checked_task_count"));
        int pipeline_count = (int)json_integer_value(json_object_get(rec, "pipeline_checked_task_count"));
        bool pipeline_valid = json_is_true(json_object_get(rec, "pipeline_valid"));
        bool deps_set = json_is_true(json_object_get(rec, "deps_set"));

        if (stats_count != task_count)
            json_array_append_new(missing, json_string("TASK_STATS"));
        if (pipeline_count != task_count)
            json_array_append_new(missing, json_string("TASK_PIPELINE_CHECK"));
        else if (!pipeline_valid)
            json_array_append_new(missing, json_string("TASK_PIPELINE_CHECK(valid_result_required)"));
        if (!deps_set)
            json_array_append_new(missing, json_string("PROJECT_DEPENDENCY_SET"));
    }

    json_decref(root);
    pthread_mutex_unlock(&g_dispatch_guard_mu);
    return missing;
}

static bool task_matches_scope(const Task *t, const char *spec_id, const char *group) {
    if (!t || !t->active) return false;
    if (spec_id && spec_id[0] && strcmp(t->spec_id, spec_id) != 0) return false;
    if (group && group[0] && strcmp(t->group, group) != 0) return false;
    return true;
}

static bool task_status_started(TaskStatus s) {
    return s == TS_IN_PROGRESS || s == TS_BLOCKED || s == TS_FAILED || s == TS_COMPLETED;
}

static const char *scope_project_id(json_t *msg_data) {
    const char *project_id = json_string_value(json_object_get(msg_data, "project_id"));
    if (!project_id || !project_id[0])
        project_id = json_string_value(json_object_get(msg_data, "spec_id"));
    return project_id;
}

static void json_inc_counter(json_t *obj, const char *field) {
    json_t *v = json_object_get(obj, field);
    json_int_t n = json_is_integer(v) ? json_integer_value(v) : 0;
    json_object_set_new(obj, field, json_integer(n + 1));
}

static json_t *find_owner_stats_entry(json_t *owner_stats, const char *owner) {
    const char *label = (owner && owner[0]) ? owner : "unassigned";
    size_t n = json_array_size(owner_stats);
    for (size_t i = 0; i < n; i++) {
        json_t *item = json_array_get(owner_stats, i);
        const char *existing = json_string_value(json_object_get(item, "owner"));
        if (existing && strcmp(existing, label) == 0) return item;
    }

    json_t *entry = json_object();
    json_object_set_new(entry, "owner", json_string(label));
    json_object_set_new(entry, "total", json_integer(0));
    json_object_set_new(entry, "pending", json_integer(0));
    json_object_set_new(entry, "in_progress", json_integer(0));
    json_object_set_new(entry, "blocked", json_integer(0));
    json_object_set_new(entry, "completed", json_integer(0));
    json_object_set_new(entry, "failed", json_integer(0));
    json_object_set_new(entry, "cancelled", json_integer(0));
    json_object_set_new(entry, "archived", json_integer(0));
    json_array_append_new(owner_stats, entry);
    return entry;
}

static void update_status_counters(json_t *summary, json_t *owner_entry, TaskStatus status) {
    const char *field = "pending";
    switch (status) {
        case TS_PENDING: field = "pending"; break;
        case TS_IN_PROGRESS: field = "in_progress"; break;
        case TS_BLOCKED: field = "blocked"; break;
        case TS_COMPLETED: field = "completed"; break;
        case TS_FAILED: field = "failed"; break;
        case TS_CANCELLED: field = "cancelled"; break;
        case TS_ARCHIVED: field = "archived"; break;
        default: break;
    }
    json_inc_counter(summary, field);
    json_inc_counter(owner_entry, field);
}

static void handle_task_stats(const char *from, const char *conv_id, json_t *msg_data) {
    const char *project_id = scope_project_id(msg_data);
    const char *group = json_string_value(json_object_get(msg_data, "group"));

    json_t *summary = json_object();
    json_object_set_new(summary, "total_tasks", json_integer(0));
    json_object_set_new(summary, "pending", json_integer(0));
    json_object_set_new(summary, "in_progress", json_integer(0));
    json_object_set_new(summary, "blocked", json_integer(0));
    json_object_set_new(summary, "completed", json_integer(0));
    json_object_set_new(summary, "failed", json_integer(0));
    json_object_set_new(summary, "cancelled", json_integer(0));
    json_object_set_new(summary, "archived", json_integer(0));
    json_t *owner_stats = json_array();

    pthread_mutex_lock(&g_task_store.mu);
    for (int i = 0; i < g_task_store.count; i++) {
        Task *t = &g_task_store.tasks[i];
        if (!task_matches_scope(t, project_id, group)) continue;

        json_inc_counter(summary, "total_tasks");
        json_t *owner_entry = find_owner_stats_entry(owner_stats, t->owner);
        json_inc_counter(owner_entry, "total");
        update_status_counters(summary, owner_entry, t->status);
    }
    pthread_mutex_unlock(&g_task_store.mu);

    json_int_t total = json_integer_value(json_object_get(summary, "total_tasks"));
    json_int_t completed = json_integer_value(json_object_get(summary, "completed"));
    double pct = (total > 0) ? (100.0 * (double)completed / (double)total) : 0.0;
    json_object_set_new(summary, "completion_pct", json_real(pct));

    json_t *scope = json_object();
    if (project_id && project_id[0]) json_object_set_new(scope, "project_id", json_string(project_id));
    if (group && group[0]) json_object_set_new(scope, "group", json_string(group));

    json_t *resp_data = json_object();
    json_object_set_new(resp_data, "scope", scope);
    json_object_set_new(resp_data, "summary", summary);
    json_object_set_new(resp_data, "owners", owner_stats);
    if (project_id && project_id[0] && spec_exists(project_id))
        dispatch_guard_mark_stats(project_id, (int)total, from);
    send_response(from, conv_id, "TASK_STATS_RESULT", "ok", resp_data);
    json_decref(resp_data);
}

static int filtered_task_index(Task **tasks, int count, const char *task_id) {
    if (!task_id || !task_id[0]) return -1;
    for (int i = 0; i < count; i++) {
        if (strcmp(tasks[i]->task_id, task_id) == 0) return i;
    }
    return -1;
}

static bool dfs_task_cycle(Task **tasks, int count, int idx,
                           int *colors, int *stack, int *stack_len,
                           json_t *cycle_path) {
    colors[idx] = 1;
    stack[*stack_len] = idx;
    (*stack_len)++;

    Task *t = tasks[idx];
    for (int i = 0; i < t->depends_count; i++) {
        int dep_idx = filtered_task_index(tasks, count, t->depends_on[i]);
        if (dep_idx < 0) continue;
        if (colors[dep_idx] == 0) {
            if (dfs_task_cycle(tasks, count, dep_idx, colors, stack, stack_len, cycle_path)) return true;
        } else if (colors[dep_idx] == 1) {
            int start = 0;
            while (start < *stack_len && stack[start] != dep_idx) start++;
            for (int j = start; j < *stack_len; j++)
                json_array_append_new(cycle_path, json_string(tasks[stack[j]]->task_id));
            json_array_append_new(cycle_path, json_string(tasks[dep_idx]->task_id));
            return true;
        }
    }

    (*stack_len)--;
    colors[idx] = 2;
    return false;
}

static void handle_task_pipeline_check(const char *from, const char *conv_id, json_t *msg_data) {
    const char *project_id = scope_project_id(msg_data);
    const char *group = json_string_value(json_object_get(msg_data, "group"));
    if (!project_id || !project_id[0]) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("missing required field: project_id or spec_id"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
        return;
    }

    Task *selected[TM_MAX_TASKS];
    int selected_count = 0;
    int edge_count = 0;
    int ready_count = 0;
    int blocked_count = 0;
    json_t *missing_deps = json_array();
    json_t *flow_violations = json_array();
    json_t *cycle_path = json_array();

    pthread_mutex_lock(&g_task_store.mu);
    for (int i = 0; i < g_task_store.count && selected_count < TM_MAX_TASKS; i++) {
        Task *t = &g_task_store.tasks[i];
        if (!task_matches_scope(t, project_id, group)) continue;
        selected[selected_count++] = t;
    }

    for (int i = 0; i < selected_count; i++) {
        Task *t = selected[i];
        bool deps_all_completed = true;
        for (int j = 0; j < t->depends_count; j++) {
            const char *dep_id = t->depends_on[j];
            edge_count++;
            int dep_idx = filtered_task_index(selected, selected_count, dep_id);
            if (dep_idx < 0) {
                deps_all_completed = false;
                json_t *m = json_object();
                json_object_set_new(m, "task_id", json_string(t->task_id));
                json_object_set_new(m, "missing_dependency", json_string(dep_id));
                json_array_append_new(missing_deps, m);
                continue;
            }
            Task *dep = selected[dep_idx];
            if (dep->status != TS_COMPLETED) deps_all_completed = false;
            if (task_status_started(t->status) && dep->status != TS_COMPLETED) {
                json_t *v = json_object();
                json_object_set_new(v, "task_id", json_string(t->task_id));
                json_object_set_new(v, "task_status", json_string(task_status_str(t->status)));
                json_object_set_new(v, "depends_on", json_string(dep->task_id));
                json_object_set_new(v, "dependency_status", json_string(task_status_str(dep->status)));
                json_array_append_new(flow_violations, v);
            }
        }
        if (t->status == TS_PENDING) {
            if (deps_all_completed) ready_count++;
            else blocked_count++;
        }
    }

    int colors[TM_MAX_TASKS];
    int stack[TM_MAX_TASKS];
    memset(colors, 0, sizeof(colors));
    int stack_len = 0;
    bool has_cycle = false;
    for (int i = 0; i < selected_count; i++) {
        if (colors[i] != 0) continue;
        if (dfs_task_cycle(selected, selected_count, i, colors, stack, &stack_len, cycle_path)) {
            has_cycle = true;
            break;
        }
    }
    pthread_mutex_unlock(&g_task_store.mu);

    bool valid = !has_cycle &&
                 json_array_size(missing_deps) == 0 &&
                 json_array_size(flow_violations) == 0;

    json_t *resp_data = json_object();
    json_object_set_new(resp_data, "project_id", json_string(project_id));
    if (group && group[0]) json_object_set_new(resp_data, "group", json_string(group));
    json_object_set_new(resp_data, "valid", valid ? json_true() : json_false());
    json_object_set_new(resp_data, "total_tasks", json_integer(selected_count));
    json_object_set_new(resp_data, "edges", json_integer(edge_count));
    json_object_set_new(resp_data, "ready_tasks", json_integer(ready_count));
    json_object_set_new(resp_data, "blocked_tasks", json_integer(blocked_count));
    json_object_set_new(resp_data, "cycle_detected", has_cycle ? json_true() : json_false());
    json_object_set_new(resp_data, "cycle_path", cycle_path);
    json_object_set_new(resp_data, "missing_dependencies", missing_deps);
    json_object_set_new(resp_data, "flow_violations", flow_violations);
    if (project_id && project_id[0] && spec_exists(project_id))
        dispatch_guard_mark_pipeline(project_id, selected_count, valid, from);
    send_response(from, conv_id, "TASK_PIPELINE_RESULT", "ok", resp_data);
    json_decref(resp_data);
}

static bool project_dep_store_path(char *buf, size_t len) {
    return compose_data_path(buf, len, "project_dependencies.json");
}

static json_t *project_dep_load_root(void) {
    char path[512];
    if (!project_dep_store_path(path, sizeof(path))) return json_object();

    json_error_t err;
    json_t *root = json_load_file(path, 0, &err);
    if (!root || !json_is_object(root)) {
        if (root) json_decref(root);
        root = json_object();
    }
    if (!json_is_object(json_object_get(root, "projects")))
        json_object_set_new(root, "projects", json_object());
    return root;
}

static int project_dep_flush_root(json_t *root) {
    char path[512];
    char tmp[520];
    if (!project_dep_store_path(path, sizeof(path))) return -1;
    if (snprintf(tmp, sizeof(tmp), "%s.tmp", path) >= (int)sizeof(tmp)) return -1;

    mkdir(cfg_data_dir, 0755);
    if (json_dump_file(root, tmp, JSON_INDENT(2) | JSON_ENSURE_ASCII) != 0) return -1;
    if (rename(tmp, path) != 0) {
        unlink(tmp);
        return -1;
    }
    return 0;
}

static bool string_array_contains(json_t *arr, const char *value) {
    if (!json_is_array(arr) || !value || !value[0]) return false;
    size_t n = json_array_size(arr);
    for (size_t i = 0; i < n; i++) {
        const char *v = json_string_value(json_array_get(arr, i));
        if (v && strcmp(v, value) == 0) return true;
    }
    return false;
}

static json_t *project_dep_normalize_list(json_t *raw, const char *project_id) {
    json_t *out = json_array();
    if (!json_is_array(raw)) return out;

    size_t n = json_array_size(raw);
    for (size_t i = 0; i < n; i++) {
        const char *dep = json_string_value(json_array_get(raw, i));
        if (!dep || !dep[0]) continue;
        if (project_id && strcmp(dep, project_id) == 0) continue;
        if (string_array_contains(out, dep)) continue;
        json_array_append_new(out, json_string(dep));
    }
    return out;
}

static json_t *project_dep_collect_downstream(json_t *projects, const char *project_id) {
    json_t *out = json_array();
    if (!json_is_object(projects) || !project_id || !project_id[0]) return out;

    const char *key;
    json_t *val;
    json_object_foreach(projects, key, val) {
        json_t *deps = json_object_get(val, "depends_on");
        if (string_array_contains(deps, project_id))
            json_array_append_new(out, json_string(key));
    }
    return out;
}

static bool project_dep_dfs_has_cycle(json_t *projects, const char *node,
                                      json_t *visiting, json_t *visited) {
    if (!node || !node[0]) return false;
    if (json_object_get(visiting, node)) return true;
    if (json_object_get(visited, node)) return false;

    json_object_set_new(visiting, node, json_true());
    json_t *rec = json_object_get(projects, node);
    json_t *deps = rec ? json_object_get(rec, "depends_on") : NULL;
    if (json_is_array(deps)) {
        size_t n = json_array_size(deps);
        for (size_t i = 0; i < n; i++) {
            const char *dep = json_string_value(json_array_get(deps, i));
            if (!dep || !dep[0]) continue;
            if (project_dep_dfs_has_cycle(projects, dep, visiting, visited)) return true;
        }
    }

    json_object_del(visiting, node);
    json_object_set_new(visited, node, json_true());
    return false;
}

static bool project_dep_cycle_for(json_t *projects, const char *project_id) {
    json_t *visiting = json_object();
    json_t *visited = json_object();
    bool has_cycle = project_dep_dfs_has_cycle(projects, project_id, visiting, visited);
    json_decref(visiting);
    json_decref(visited);
    return has_cycle;
}

static void handle_project_dependency_set(const char *from, const char *conv_id, json_t *msg_data) {
    const char *project_id = scope_project_id(msg_data);
    if (!project_id || !project_id[0]) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("missing required field: project_id or spec_id"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
        return;
    }

    const char *updated_by = json_string_value(json_object_get(msg_data, "updated_by"));
    if (!updated_by || !updated_by[0]) updated_by = from;
    json_t *depends_on_raw = json_object_get(msg_data, "depends_on");

    pthread_mutex_lock(&g_project_dep_mu);
    json_t *root = project_dep_load_root();
    json_t *projects = json_object_get(root, "projects");
    json_t *deps = project_dep_normalize_list(depends_on_raw, project_id);

    json_t *rec = json_object();
    json_object_set_new(rec, "project_id", json_string(project_id));
    json_object_set_new(rec, "depends_on", deps);
    char ts[32];
    now_iso(ts, sizeof(ts));
    json_object_set_new(rec, "updated_at", json_string(ts));
    json_object_set_new(rec, "updated_by", json_string(updated_by));
    json_object_set_new(projects, project_id, rec);

    int rc = project_dep_flush_root(root);
    if (rc != 0) {
        pthread_mutex_unlock(&g_project_dep_mu);
        json_decref(root);
        json_t *e = json_array();
        json_array_append_new(e, json_string("failed to persist project dependency graph"));
        send_error(from, conv_id, "TASK_REJECTED", e);
        json_decref(e);
        return;
    }

    json_t *stored = json_object_get(projects, project_id);
    json_t *downstream = project_dep_collect_downstream(projects, project_id);
    bool has_cycle = project_dep_cycle_for(projects, project_id);

    json_t *resp = json_object();
    json_object_set_new(resp, "project_id", json_string(project_id));
    json_object_set(resp, "depends_on", json_object_get(stored, "depends_on"));
    json_object_set_new(resp, "required_by", downstream);
    json_object_set_new(resp, "cycle_detected", has_cycle ? json_true() : json_false());
    json_object_set(resp, "updated_at", json_object_get(stored, "updated_at"));
    json_object_set(resp, "updated_by", json_object_get(stored, "updated_by"));
    if (spec_exists(project_id))
        dispatch_guard_mark_dependencies(project_id, updated_by);

    pthread_mutex_unlock(&g_project_dep_mu);
    json_decref(root);
    send_response(from, conv_id, "PROJECT_DEPENDENCY_UPDATED", "ok", resp);
    json_decref(resp);
}

static void handle_project_dependency_query(const char *from, const char *conv_id, json_t *msg_data) {
    const char *project_id = scope_project_id(msg_data);

    pthread_mutex_lock(&g_project_dep_mu);
    json_t *root = project_dep_load_root();
    json_t *projects = json_object_get(root, "projects");
    json_t *resp = json_object();

    if (project_id && project_id[0]) {
        json_t *rec = json_object_get(projects, project_id);
        json_t *downstream = project_dep_collect_downstream(projects, project_id);
        bool has_cycle = project_dep_cycle_for(projects, project_id);

        json_object_set_new(resp, "project_id", json_string(project_id));
        json_object_set_new(resp, "exists", rec ? json_true() : json_false());
        if (rec) {
            json_object_set(resp, "depends_on", json_object_get(rec, "depends_on"));
            json_object_set(resp, "updated_at", json_object_get(rec, "updated_at"));
            json_object_set(resp, "updated_by", json_object_get(rec, "updated_by"));
        } else {
            json_object_set_new(resp, "depends_on", json_array());
        }
        json_object_set_new(resp, "required_by", downstream);
        json_object_set_new(resp, "cycle_detected", has_cycle ? json_true() : json_false());
    } else {
        json_t *items = json_array();
        int edge_count = 0;
        const char *key;
        json_t *val;
        json_object_foreach(projects, key, val) {
            json_t *item = json_object();
            json_t *deps = json_object_get(val, "depends_on");
            json_t *downstream = project_dep_collect_downstream(projects, key);
            size_t dep_n = json_is_array(deps) ? json_array_size(deps) : 0;
            edge_count += (int)dep_n;

            json_object_set_new(item, "project_id", json_string(key));
            if (deps) json_object_set(item, "depends_on", deps);
            else json_object_set_new(item, "depends_on", json_array());
            json_object_set_new(item, "required_by_count", json_integer((json_int_t)json_array_size(downstream)));
            json_object_set_new(item, "cycle_detected", project_dep_cycle_for(projects, key) ? json_true() : json_false());
            json_array_append_new(items, item);
            json_decref(downstream);
        }
        json_object_set_new(resp, "projects", items);
        json_object_set_new(resp, "total_projects", json_integer((json_int_t)json_array_size(items)));
        json_object_set_new(resp, "total_edges", json_integer(edge_count));
    }

    pthread_mutex_unlock(&g_project_dep_mu);
    json_decref(root);
    send_response(from, conv_id, "PROJECT_DEPENDENCY_RESULT", "ok", resp);
    json_decref(resp);
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

    if (cfg_check_owner_online) {
        int owner_state = owner_online_state(t.owner);
        if (owner_state <= 0) {
            json_t *e = json_array();
            if (owner_state == 0) {
                json_array_append_new(e, json_string("owner is not online or not registered"));
            } else {
                json_array_append_new(e, json_string("failed to verify owner online state"));
            }
            send_error(from, conv_id, "TASK_REJECTED", e);
            json_decref(e);
            return;
        }
    }

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
    const char *new_owner = json_string_value(json_object_get(msg_data, "owner"));
    if (cfg_check_owner_online && new_owner && new_owner[0]) {
        int owner_state = owner_online_state(new_owner);
        if (owner_state <= 0) {
            json_t *e = json_array();
            json_array_append_new(e, json_string("updated owner is not online or not registered"));
            send_error(from, conv_id, "TASK_REJECTED", e);
            json_decref(e);
            return;
        }
    }

    json_t *errs = validate_task_update(msg_data, &g_task_store);
    if (errs) {
        tm_log("WARN", "TASK_UPDATE rejected from %s", from);
        send_error(from, conv_id, "TASK_REJECTED", errs);
        json_decref(errs);
        return;
    }

    const char *task_id = json_string_value(json_object_get(msg_data, "task_id"));
    const char *new_status = json_string_value(json_object_get(msg_data, "status"));
    Task *current = task_store_get(&g_task_store, task_id);
    if (new_status && strcmp(new_status, "in_progress") == 0 &&
        current && current->spec_id[0] && spec_exists(current->spec_id)) {
        int task_count = count_tasks_for_project(current->spec_id);
        json_t *missing = dispatch_guard_missing_checks(current->spec_id, task_count);
        if (json_array_size(missing) > 0) {
            json_t *e = json_array();
            json_array_append_new(e, json_string("dispatch guard rejected: call required task-manager checks before TASK_UPDATE->in_progress"));
            size_t n = json_array_size(missing);
            for (size_t i = 0; i < n; i++) {
                const char *need = json_string_value(json_array_get(missing, i));
                if (!need) continue;
                char buf[256];
                snprintf(buf, sizeof(buf), "missing guard check: %s", need);
                json_array_append_new(e, json_string(buf));
            }
            send_error(from, conv_id, "TASK_REJECTED", e);
            json_decref(e);
            json_decref(missing);
            return;
        }
        json_decref(missing);
    }

    int rc = task_store_update(&g_task_store, task_id, msg_data);
    if (rc == 0) {
        tm_log("INFO", "TASK_UPDATED: %s", task_id);
        Task *t = task_store_get(&g_task_store, task_id);
        json_t *result = t ? task_to_json(t) : json_object();
        send_response(from, conv_id, "TASK_UPDATED", "ok", result);
        json_decref(result);
        if (t) maybe_trigger_task_knowledge_sync(t);
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

static void build_spec_intake_task(Task *t,
                                   const char *spec_id,
                                   const char *title,
                                   const char *group,
                                   const char *owner) {
    memset(t, 0, sizeof(*t));
    t->active = true;
    snprintf(t->task_id, sizeof(t->task_id), "%s-T001", spec_id);
    snprintf(t->title, sizeof(t->title), "Kickoff: %s", title);
    snprintf(t->owner, sizeof(t->owner), "%s", owner);
    snprintf(t->priority, sizeof(t->priority), "high");
    snprintf(t->spec_id, sizeof(t->spec_id), "%s", spec_id);
    snprintf(t->group, sizeof(t->group), "%s", group);
    snprintf(t->description, sizeof(t->description),
             "Spec intake baseline task. Refine 06_tasks.yaml and keep task list synchronized in task_manager.");
    snprintf(t->tags[0], sizeof(t->tags[0]), "project-intake");
    snprintf(t->tags[1], sizeof(t->tags[1]), "tasklist-required");
    t->tags_count = 2;
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

    if (g_task_store.count >= TM_MAX_TASKS) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("task store is full, cannot create intake task"));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
        return;
    }

    Task intake_task;
    build_spec_intake_task(&intake_task, spec_id, title, group, owner);
    if (task_store_get(&g_task_store, intake_task.task_id)) {
        json_t *e = json_array();
        json_array_append_new(e, json_string("intake task_id already exists"));
        send_error(from, conv_id, "SPEC_REJECTED", e);
        json_decref(e);
        return;
    }

    int task_rc = task_store_create(&g_task_store, &intake_task);
    if (task_rc != 0) {
        tm_log("ERROR", "intake task create failed: spec=%s rc=%d", spec_id, task_rc);
        json_t *e = json_array();
        json_array_append_new(e, json_string("failed to create intake task record"));
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
        json_object_set_new(result, "intake_task_id", json_string(intake_task.task_id));
        char task_list_path[512];
        snprintf(task_list_path, sizeof(task_list_path),
                 "/brain/groups/org/%s/spec/%s/06_tasks.yaml", group, spec_id);
        json_object_set_new(result, "task_list_path", json_string(task_list_path));
        send_response(from, conv_id, "SPEC_CREATED", "ok", result);
        json_decref(result);
    } else {
        /* Roll back intake task if spec creation failed. */
        (void)task_store_delete(&g_task_store, intake_task.task_id);
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
        SpecRecord *r = spec_store_get(&g_spec_store, spec_id);
        json_t *result = json_object();
        json_object_set_new(result, "spec_id", json_string(spec_id));
        json_object_set_new(result, "stage", json_string(r ? spec_stage_str(r->stage) : stage));
        send_response(from, conv_id, "SPEC_ADVANCED", "ok", result);
        json_decref(result);
        if (r) maybe_trigger_spec_knowledge_sync(r);
    } else {
        const char *reason = "unknown";
        if (rc == -1) reason = "spec not found";
        else if (rc == -3) reason = "cannot go backward";
        else if (rc == -4) reason = "cannot skip stages";
        else if (rc == -5) reason = "missing 06_tasks.yaml artifact";
        else if (rc == -6) reason = "06_tasks.yaml has no task_id entries";
        else if (rc == -7) reason = "all tasks in 06_tasks.yaml must have explicit agent owner";
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
    char *body = build_health_json_body();
    json_error_t err;
    json_t *result = body ? json_loads(body, 0, &err) : NULL;
    if (!result) result = json_object();
    free(body);
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
    else if (strcmp(event_type, "TASK_STATS") == 0)
        handle_task_stats(from, conv_id, data);
    else if (strcmp(event_type, "TASK_PIPELINE_CHECK") == 0)
        handle_task_pipeline_check(from, conv_id, data);
    else if (strcmp(event_type, "TASK_DELETE") == 0)
        handle_task_delete(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_CREATE") == 0)
        handle_spec_create(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_PROGRESS") == 0)
        handle_spec_progress(from, conv_id, data);
    else if (strcmp(event_type, "SPEC_QUERY") == 0)
        handle_spec_query(from, conv_id, data);
    else if (strcmp(event_type, "PROJECT_DEPENDENCY_SET") == 0)
        handle_project_dependency_set(from, conv_id, data);
    else if (strcmp(event_type, "PROJECT_DEPENDENCY_QUERY") == 0)
        handle_project_dependency_query(from, conv_id, data);
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
            else if (strcmp(key, "health_port") == 0)
                cfg_health_port = atoi(val);
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
            else if (strcmp(key, "check_owner_online") == 0)
                cfg_check_owner_online = is_true_like(val);
        }
    }
    fclose(f);
}

/* ══════════════════════════════════════════════
 *  Main
 * ══════════════════════════════════════════════ */

int main(int argc, char **argv) {
    /* Config path: argv[1] or default */
    const char *config_path = "/brain/infrastructure/service/task_manager/config/task_manager.yaml";
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
    int register_backoff_s = 1;
    while (!g_shutdown) {
        if (ipc_register()) {
            tm_log("INFO", "registered as %s", cfg_agent_name);
            break;
        }
        retry++;
        tm_log("WARN", "register failed, retry #%d in %ds...", retry, register_backoff_s);
        sleep((unsigned int)register_backoff_s);
        if (register_backoff_s < 30) {
            register_backoff_s *= 2;
            if (register_backoff_s > 30) register_backoff_s = 30;
        }
    }
    if (g_shutdown) return 0;

    start_health_server();

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
    if (g_health_fd >= 0) close(g_health_fd);
    if (g_health_thread_started) pthread_join(g_health_thread, NULL);

    /* ── Graceful shutdown ── */
    tm_log("INFO", "shutting down...");
    task_store_flush(&g_task_store);
    spec_store_flush(&g_spec_store);
    tm_log("INFO", "data flushed, exiting");

    if (g_logfile && g_logfile != stderr)
        fclose(g_logfile);

    return 0;
}
