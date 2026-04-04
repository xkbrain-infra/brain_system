/*
 * Brain Daemon v2 - C Implementation
 * High-performance brain_ipc for Agent communication
 *
 * Features:
 * - Unix socket server (JSON protocol)
 * - Agent registry with instance_id support
 * - Message queue with ACK/retry/deadletter
 * - Delayed message scheduling
 * - Conversation management
 * - Tmux discovery and push notifications
 * - Business handlers (audit, lep, pre_write, pre_bash)
 * - Thread-safe operations
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <pthread.h>
#include <jansson.h>
#include <time.h>
#include <fcntl.h>
#include <stdarg.h>

#include "msgqueue.h"
#include "agent_registry.h"
#include "delayed_queue.h"
#include "conversation.h"
#include "scheduled_queue.h"

#define SOCKET_PATH "/tmp/brain_ipc.sock"
#define PID_FILE "/tmp/brain_ipc.pid"
#define LOG_FILE_DEFAULT "/tmp/brain_ipc_daemon.log"
#define NOTIFY_SOCKET_DEFAULT "/tmp/brain_ipc_notify.sock"
#define MAX_CLIENTS 64
#define BUFFER_SIZE 65536
#define SELF_SERVICE_NAME "service-brain_ipc"

// Tmux discovery config
#define TMUX_DISCOVERY_INTERVAL 2
#define TMUX_SEND_BIN "/brain/infrastructure/service/utils/tmux/bin/brain_tmux_send"

// Agent name prefixes for tmux discovery
static const char *TMUX_AGENT_PREFIXES[] = {"claude", "codex", "codex-cli", NULL};

// Global state
static volatile int g_shutdown = 0;
static MsgQueue g_msgqueue;
static AgentRegistry g_registry;
static DelayedQueue g_delayed_queue;
static ConversationManager g_conversation_manager;
static scheduled_queue_t g_scheduled_queue;
static FILE *g_logfile = NULL;
static time_t g_start_time = 0;
// Tmux send-keys notification for agent wake-up on new IPC messages.
// Default: enabled. Set BRAIN_TMUX_NOTIFY=0 to disable.
static int g_tmux_notify_enabled = 1;

static int env_bool(const char *name, int default_value) {
    const char *v = getenv(name);
    if (!v || !v[0]) return default_value;
    if (strcmp(v, "1") == 0 || strcasecmp(v, "true") == 0 || strcasecmp(v, "yes") == 0 || strcasecmp(v, "on") == 0) return 1;
    if (strcmp(v, "0") == 0 || strcasecmp(v, "false") == 0 || strcasecmp(v, "no") == 0 || strcasecmp(v, "off") == 0) return 0;
    return default_value;
}

// ============ Notify Socket (brain_ipc -> MCP server wake-up) ============

static void ipc_log(const char *level, const char *fmt, ...);
static const char *derive_agent_name_from_session(const char *session_name);

static bool is_valid_tmux_pane_id(const char *pane) {
    if (!pane || !pane[0]) return false;
    if (pane[0] != '%') return false;
    // Must be like %123 (digits after %)
    for (const char *p = pane + 1; *p; p++) {
        if (*p < '0' || *p > '9') return false;
    }
    return true;
}

static char g_notify_socket_path[512] = {0};
static int g_notify_server_fd = -1;
static int g_notify_clients[128];
static int g_notify_client_count = 0;
static pthread_mutex_t g_notify_mu = PTHREAD_MUTEX_INITIALIZER;

static void ensure_parent_dir(const char *path) {
    if (!path || !path[0]) return;
    char buf[512];
    snprintf(buf, sizeof(buf), "%s", path);
    char *slash = strrchr(buf, '/');
    if (!slash) return;
    *slash = '\0';
    if (!buf[0]) return;

    // mkdir -p
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "%s", buf);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    mkdir(tmp, 0755);
}

static void notify_clients_compact_locked(void) {
    int w = 0;
    for (int i = 0; i < g_notify_client_count; i++) {
        if (g_notify_clients[i] >= 0) {
            g_notify_clients[w++] = g_notify_clients[i];
        }
    }
    g_notify_client_count = w;
}

static void notify_broadcast_line(const char *line) {
    if (!line || !line[0]) return;
    pthread_mutex_lock(&g_notify_mu);
    for (int i = 0; i < g_notify_client_count; i++) {
        int fd = g_notify_clients[i];
        if (fd < 0) continue;
        ssize_t n = send(fd, line, strlen(line), MSG_NOSIGNAL);
        if (n < 0) {
            close(fd);
            g_notify_clients[i] = -1;
        }
    }
    notify_clients_compact_locked();
    pthread_mutex_unlock(&g_notify_mu);
}

static void* notify_accept_thread(void *arg) {
    (void)arg;
    while (!g_shutdown && g_notify_server_fd >= 0) {
        int cfd = accept(g_notify_server_fd, NULL, NULL);
        if (cfd < 0) {
            if (errno == EINTR) continue;
            usleep(50 * 1000);
            continue;
        }
        pthread_mutex_lock(&g_notify_mu);
        if (g_notify_client_count < (int)(sizeof(g_notify_clients) / sizeof(g_notify_clients[0]))) {
            g_notify_clients[g_notify_client_count++] = cfd;
        } else {
            close(cfd);
        }
        pthread_mutex_unlock(&g_notify_mu);
    }
    return NULL;
}

static void notify_server_start(void) {
    const char *p = getenv("BRAIN_IPC_NOTIFY_SOCKET");
    if (!p || !p[0]) p = NOTIFY_SOCKET_DEFAULT;
    snprintf(g_notify_socket_path, sizeof(g_notify_socket_path), "%s", p);

    ensure_parent_dir(g_notify_socket_path);
    unlink(g_notify_socket_path);

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        ipc_log("WARN", "notify socket() failed: %s", strerror(errno));
        return;
    }
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, g_notify_socket_path, sizeof(addr.sun_path) - 1);
    if (bind(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        ipc_log("WARN", "notify bind(%s) failed: %s", g_notify_socket_path, strerror(errno));
        close(fd);
        return;
    }
    if (listen(fd, 64) < 0) {
        ipc_log("WARN", "notify listen() failed: %s", strerror(errno));
        close(fd);
        unlink(g_notify_socket_path);
        return;
    }
    g_notify_server_fd = fd;

    pthread_t tid;
    if (pthread_create(&tid, NULL, notify_accept_thread, NULL) == 0) {
        pthread_detach(tid);
        ipc_log("INFO", "Notify socket ready: %s", g_notify_socket_path);
    } else {
        ipc_log("WARN", "notify pthread_create failed");
    }
}

static void notify_server_shutdown(void) {
    pthread_mutex_lock(&g_notify_mu);
    for (int i = 0; i < g_notify_client_count; i++) {
        if (g_notify_clients[i] >= 0) close(g_notify_clients[i]);
        g_notify_clients[i] = -1;
    }
    g_notify_client_count = 0;
    pthread_mutex_unlock(&g_notify_mu);

    if (g_notify_server_fd >= 0) close(g_notify_server_fd);
    g_notify_server_fd = -1;
    if (g_notify_socket_path[0]) unlink(g_notify_socket_path);
}

// ============ Logging ============

static void ipc_log(const char *level, const char *fmt, ...) {
    if (!g_logfile) return;

    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    char timebuf[32];
    strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", tm);

    fprintf(g_logfile, "[%s] [%s] ", timebuf, level);

    va_list args;
    va_start(args, fmt);
    vfprintf(g_logfile, fmt, args);
    va_end(args);

    fprintf(g_logfile, "\n");
    fflush(g_logfile);
}

#define LOG_INFO(...)  ipc_log("INFO", __VA_ARGS__)
#define LOG_ERROR(...) ipc_log("ERROR", __VA_ARGS__)
#define LOG_WARN(...)  ipc_log("WARN", __VA_ARGS__)

// ============ Signal Handler ============

static void signal_handler(int sig) {
    (void)sig;
    g_shutdown = 1;
}

// ============ JSON Helpers ============

static char* json_ok(const char *extra) {
    char *buf = malloc(BUFFER_SIZE);
    if (extra && extra[0]) {
        snprintf(buf, BUFFER_SIZE, "{\"status\":\"ok\",%s}\n", extra);
    } else {
        snprintf(buf, BUFFER_SIZE, "{\"status\":\"ok\"}\n");
    }
    return buf;
}

static char* json_error(const char *msg) {
    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE, "{\"status\":\"error\",\"message\":\"%s\"}\n", msg);
    return buf;
}

// ============ Handler: ping ============

static char* handle_ping(json_t *data) {
    (void)data;
    char extra[256];
    snprintf(extra, sizeof(extra), "\"pong\":true,\"uptime\":%ld,\"version\":\"2.0\"",
             (long)(time(NULL) - g_start_time));
    return json_ok(extra);
}

// ============ Agent Registry Handlers ============

static char* handle_agent_register(json_t *data) {
    const char *name = json_string_value(json_object_get(data, "agent_name"));
    const char *tmux_pane = json_string_value(json_object_get(data, "tmux_pane"));
    const char *tmux_session = json_string_value(json_object_get(data, "tmux_session"));
    json_t *metadata_obj = json_object_get(data, "metadata");
    char *metadata = metadata_obj ? json_dumps(metadata_obj, JSON_COMPACT) : NULL;

    if (!name || !name[0]) {
        if (metadata) free(metadata);
        return json_error("missing agent_name");
    }

    if (!tmux_session || !tmux_session[0]) {
        if (metadata) free(metadata);
        return json_error("missing tmux_session");
    }
    if (!tmux_pane || !tmux_pane[0]) {
        if (metadata) free(metadata);
        return json_error("missing tmux_pane");
    }
    if (!is_valid_tmux_pane_id(tmux_pane)) {
        if (metadata) free(metadata);
        return json_error("invalid tmux_pane (expected like %2)");
    }

    /*
     * Sandbox agents may occasionally mis-register using their sbx_<instance>__
     * tmux session alias as agent_name. Canonicalize register/heartbeat traffic
     * to the logical agent name carried after "__" so queue routing stays
     * stable even when the client submits the wrong alias.
     */
    const char *canonical_name = name;
    const char *derived_name = derive_agent_name_from_session(tmux_session);
    if (derived_name && derived_name[0] && strncmp(tmux_session, "sbx_", 4) == 0) {
        canonical_name = derived_name;
    }

    registry_register_full(&g_registry, canonical_name, tmux_session, tmux_pane, metadata, AGENT_SOURCE_REGISTER);
    LOG_INFO("Agent registered: %s (session=%s, pane=%s)",
             canonical_name, tmux_session ? tmux_session : "none", tmux_pane ? tmux_pane : "none");

    if (metadata) free(metadata);

    char instance_id[MAX_INSTANCE_ID];
    build_instance_id(instance_id, sizeof(instance_id), canonical_name, tmux_session, tmux_pane);

    char extra[512];
    snprintf(extra, sizeof(extra), "\"agent\":\"%s\",\"agent_id\":\"%s\",\"registered_at\":%ld",
             canonical_name, instance_id, (long)time(NULL));
    return json_ok(extra);
}

static char* handle_agent_heartbeat(json_t *data) {
    const char *name = json_string_value(json_object_get(data, "agent_name"));
    const char *tmux_session = json_string_value(json_object_get(data, "tmux_session"));
    const char *tmux_pane = json_string_value(json_object_get(data, "tmux_pane"));

    if (!name || !name[0]) {
        return json_error("missing agent_name");
    }

    if (!tmux_session || !tmux_session[0]) {
        return json_error("missing tmux_session");
    }
    if (!tmux_pane || !tmux_pane[0]) {
        return json_error("missing tmux_pane");
    }
    if (!is_valid_tmux_pane_id(tmux_pane)) {
        return json_error("invalid tmux_pane (expected like %2)");
    }

    const char *canonical_name = name;
    const char *derived_name = derive_agent_name_from_session(tmux_session);
    if (derived_name && derived_name[0] && strncmp(tmux_session, "sbx_", 4) == 0) {
        canonical_name = derived_name;
    }

    registry_heartbeat_full(&g_registry, canonical_name, tmux_session, tmux_pane);

    char instance_id[MAX_INSTANCE_ID];
    build_instance_id(instance_id, sizeof(instance_id), canonical_name, tmux_session, tmux_pane);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"agent\":\"%s\",\"agent_id\":\"%s\",\"heartbeat_at\":%ld",
             canonical_name, instance_id, (long)time(NULL));
    return json_ok(extra);
}

// ============ Service Registration (no tmux required) ============

/* Walk up the process tree to find the first /dev/pts/N PTY */
static int find_pty_for_pid(pid_t start_pid, char *buf, size_t sz) {
    pid_t pid = start_pid;
    for (int depth = 0; depth < 10 && pid > 1; depth++) {
        char fd0[64];
        snprintf(fd0, sizeof(fd0), "/proc/%d/fd/0", (int)pid);
        char target[256];
        ssize_t len = readlink(fd0, target, sizeof(target) - 1);
        if (len > 0) {
            target[len] = '\0';
            if (strncmp(target, "/dev/pts/", 9) == 0) {
                snprintf(buf, sz, "%s", target);
                return 1;
            }
        }
        /* Read ppid from /proc/pid/stat: "pid (comm) state ppid ..." */
        char stat_path[64];
        snprintf(stat_path, sizeof(stat_path), "/proc/%d/stat", (int)pid);
        FILE *f = fopen(stat_path, "r");
        if (!f) break;
        char line[256];
        pid_t ppid = 0;
        if (fgets(line, sizeof(line), f)) {
            /* Format: pid (comm) state ppid — skip past closing ')' for comm */
            char *rp = strrchr(line, ')');
            if (rp) sscanf(rp + 1, " %*c %d", &ppid);
        }
        fclose(f);
        if (ppid <= 1) break;
        pid = ppid;
    }
    LOG_INFO("find_pty_for_pid: no PTY found for pid=%d (walked up from %d)", (int)pid, (int)start_pid);
    return 0;
}

static char* handle_service_register(json_t *data, int client_fd) {
    const char *name = json_string_value(json_object_get(data, "service_name"));
    const char *pty_path = json_string_value(json_object_get(data, "pty_path"));
    json_t *metadata_obj = json_object_get(data, "metadata");
    char *metadata = metadata_obj ? json_dumps(metadata_obj, JSON_COMPACT) : NULL;

    if (!name || !name[0]) {
        if (metadata) free(metadata);
        return json_error("missing service_name");
    }

    // Auto-discover PTY via SO_PEERCRED if not provided by client
    char discovered_pty[256] = {0};
    if ((!pty_path || !pty_path[0]) && client_fd >= 0) {
        struct ucred cred;
        socklen_t cred_len = sizeof(cred);
        if (getsockopt(client_fd, SOL_SOCKET, SO_PEERCRED, &cred, &cred_len) == 0) {
            if (find_pty_for_pid(cred.pid, discovered_pty, sizeof(discovered_pty))) {
                pty_path = discovered_pty;
                LOG_INFO("Auto-discovered PTY for %s (pid=%d): %s", name, (int)cred.pid, pty_path);
            }
        }
    }

    // Service registers with no tmux — instance_id is just the name
    registry_register_full(&g_registry, name, NULL, NULL, metadata, AGENT_SOURCE_SERVICE);
    LOG_INFO("Service registered: %s (pty=%s)", name, pty_path ? pty_path : "none");

    // Store pty_path if provided or discovered (for non-tmux push notifications)
    if (pty_path && pty_path[0]) {
        pthread_mutex_lock(&g_registry.lock);
        for (int i = 0; i < g_registry.count; i++) {
            Agent *a = &g_registry.agents[i];
            if (a->active && a->source == AGENT_SOURCE_SERVICE &&
                strcmp(a->name, name) == 0) {
                strncpy(a->pty_path, pty_path, MAX_PTY_PATH - 1);
                a->pty_path[MAX_PTY_PATH - 1] = '\0';
                break;
            }
        }
        pthread_mutex_unlock(&g_registry.lock);
    }

    if (metadata) free(metadata);

    char extra[512];
    snprintf(extra, sizeof(extra), "\"service\":\"%s\",\"pty_path\":\"%s\",\"registered_at\":%ld",
             name, pty_path ? pty_path : "", (long)time(NULL));
    return json_ok(extra);
}

static char* handle_service_heartbeat(json_t *data) {
    const char *name = json_string_value(json_object_get(data, "service_name"));

    if (!name || !name[0]) {
        return json_error("missing service_name");
    }

    // Find existing entry (regardless of source) and update heartbeat
    pthread_mutex_lock(&g_registry.lock);
    Agent *a = NULL;
    for (int i = 0; i < g_registry.count; i++) {
        if (g_registry.agents[i].active &&
            strcmp(g_registry.agents[i].name, name) == 0) {
            a = &g_registry.agents[i];
            break;
        }
    }
    if (a) {
        a->last_heartbeat = time(NULL);
        // Normalize source so future service heartbeats are treated consistently.
        a->source = AGENT_SOURCE_SERVICE;
    } else {
        // Not registered yet — auto-register
        pthread_mutex_unlock(&g_registry.lock);
        registry_register_full(&g_registry, name, NULL, NULL, NULL, AGENT_SOURCE_SERVICE);
        LOG_INFO("Service auto-registered via heartbeat: %s", name);
        char extra[256];
        snprintf(extra, sizeof(extra), "\"service\":\"%s\",\"heartbeat_at\":%ld",
                 name, (long)time(NULL));
        return json_ok(extra);
    }
    pthread_mutex_unlock(&g_registry.lock);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"service\":\"%s\",\"heartbeat_at\":%ld",
             name, (long)time(NULL));
    return json_ok(extra);
}

static char* handle_agent_list(json_t *data) {
    int include_offline = 0;
    json_t *offline_val = json_object_get(data, "include_offline");
    if (offline_val && json_is_true(offline_val)) {
        include_offline = 1;
    }

    char agents_json[16384];
    char instances_json[16384];
    int count = registry_list_online(&g_registry, agents_json, sizeof(agents_json));
    int inst_count = registry_list_instances(&g_registry, instances_json, sizeof(instances_json), include_offline);

    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE,
             "{\"status\":\"ok\",\"agents\":%s,\"instances\":%s,\"count\":%d,\"instance_count\":%d}\n",
             agents_json, instances_json, count, inst_count);
    return buf;
}

static char* handle_agent_unregister(json_t *data) {
    const char *name = json_string_value(json_object_get(data, "agent_name"));
    const char *instance_id = json_string_value(json_object_get(data, "instance_id"));

    if (instance_id && instance_id[0]) {
        int result = registry_unregister_instance(&g_registry, instance_id);
        LOG_INFO("Agent instance unregistered: %s", instance_id);
        char extra[256];
        snprintf(extra, sizeof(extra), "\"instance_id\":\"%s\",\"unregistered\":%s",
                 instance_id, result == 0 ? "true" : "false");
        return json_ok(extra);
    }

    if (!name || !name[0]) {
        return json_error("missing agent_name or instance_id");
    }

    int result = registry_unregister(&g_registry, name);
    LOG_INFO("Agent unregistered: %s", name);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"agent\":\"%s\",\"unregistered\":%s",
             name, result == 0 ? "true" : "false");
    return json_ok(extra);
}

// ============ Tmux Push Notification ============

static void trim_in_place(char *s) {
    if (!s) return;
    size_t n = strlen(s);
    while (n > 0) {
        char c = s[n - 1];
        if (c == '\n' || c == '\r' || c == ' ' || c == '\t') {
            s[--n] = '\0';
            continue;
        }
        break;
    }
}

static int parse_sandbox_instance_id(const char *tmux_session, char *instance_id, size_t size) {
    if (!tmux_session || strncmp(tmux_session, "sbx_", 4) != 0) return -1;

    const char *start = tmux_session + 4;
    const char *sep = strstr(start, "__");
    if (!sep || sep == start) return -1;

    size_t len = (size_t)(sep - start);
    if (len >= size) len = size - 1;
    memcpy(instance_id, start, len);
    instance_id[len] = '\0';
    return 0;
}

static int read_sandbox_container_name(const char *instance_id, char *container_name, size_t size) {
    if (!instance_id || !instance_id[0] || !container_name || size == 0) return -1;

    char path[512];
    snprintf(path, sizeof(path), "/xkagent_infra/runtime/sandbox/%s/.bootstrap/instance.yaml", instance_id);

    FILE *fp = fopen(path, "r");
    if (!fp) return -1;

    char line[1024];
    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "container_name:", 15) != 0) continue;
        char *value = line + 15;
        while (*value == ' ' || *value == '\t') value++;
        trim_in_place(value);
        if (value[0]) {
            snprintf(container_name, size, "%s", value);
            fclose(fp);
            return 0;
        }
    }

    fclose(fp);
    return -1;
}

static int spawn_container_tmux_notify(const char *tmux_session, const char *pane, const char *from, const char *msg_id) {
    char instance_id[128];
    char container_name[256];
    char tmux_tmpdir[512];
    char tmux_tmpdir_env[544];
    char prompt[512];

    if (parse_sandbox_instance_id(tmux_session, instance_id, sizeof(instance_id)) != 0) return -1;
    if (read_sandbox_container_name(instance_id, container_name, sizeof(container_name)) != 0) return -1;

    snprintf(tmux_tmpdir, sizeof(tmux_tmpdir), "/xkagent_infra/runtime/sandbox/%s/.tmux", instance_id);
    snprintf(tmux_tmpdir_env, sizeof(tmux_tmpdir_env), "TMUX_TMPDIR=%s", tmux_tmpdir);
    snprintf(prompt, sizeof(prompt),
        "[IPC] New message from %s (msg_id=%s). Call ipc_recv to get messages, then ipc_send to reply. These are MCP tools, NOT shell commands.",
        from ? from : "unknown", msg_id);

    pid_t pid = fork();
    if (pid == 0) {
        setenv("BRAIN_TMUX_CONTAINER", container_name, 1);
        setenv("TMUX_TMPDIR", tmux_tmpdir, 1);
        if (access(TMUX_SEND_BIN, X_OK) == 0) {
            execl(TMUX_SEND_BIN, "brain_tmux_send", "-t", pane, "--no-clear", "--double-enter", "--no-audit", prompt, NULL);
        }
        execlp("docker", "docker", "exec", "-i", container_name,
               "env", tmux_tmpdir_env,
               "tmux", "send-keys", "-t", pane, prompt, "C-m", "C-m", NULL);
        _exit(1);
    }
    if (pid < 0) return -1;
    return 0;
}

static void tmux_notify(const char *tmux_session, const char *pane, const char *from, const char *msg_id) {
    if (!pane || !pane[0]) return;

    if (tmux_session && tmux_session[0] && strncmp(tmux_session, "sbx_", 4) == 0) {
        if (spawn_container_tmux_notify(tmux_session, pane, from, msg_id) == 0) {
            return;
        }
        LOG_WARN("sandbox tmux notify fallback to host: session=%s pane=%s", tmux_session, pane);
    }

    pid_t pid = fork();
    if (pid == 0) {
        char prompt[512];
        snprintf(prompt, sizeof(prompt),
            "[IPC] New message from %s (msg_id=%s). Call ipc_recv to get messages, then ipc_send to reply. These are MCP tools, NOT shell commands.",
            from ? from : "unknown", msg_id);

        if (access(TMUX_SEND_BIN, X_OK) == 0) {
            /* --no-clear: skip Escape+C-u which interrupts busy agents.
               --double-enter: needed for Claude Code TUI to submit input. */
            execl(TMUX_SEND_BIN, "brain_tmux_send", "-t", pane, "--no-clear", "--double-enter", "--no-audit", prompt, NULL);
        }
        /* Fallback: send text + Enter, no Escape */
        execlp("tmux", "tmux", "send-keys", "-t", pane, prompt, "C-m", "C-m", NULL);
        _exit(1);
    }
}

// Unified notification: tmux_pane only
static void notify_agent(const Agent *agent, const char *from, const char *msg_id) {
    if (!agent) return;
    if (agent->tmux_pane[0]) {
        tmux_notify(agent->tmux_session, agent->tmux_pane, from, msg_id);
    }
}

// ============ Scheduled Queue Callback ============

static void sched_send_callback(const char *to, const char *payload, const char *msg_type) {
    // Resolve target
    char resolved[MAX_INSTANCE_ID];
    Agent *target = NULL;
    char error_msg[256] = {0};

    if (resolve_target(&g_registry, to, resolved, sizeof(resolved), &target, error_msg, sizeof(error_msg)) != 0) {
        // If resolution fails, use original name
        strncpy(resolved, to, sizeof(resolved) - 1);
    }

    // Create message
    Message *msg = message_create_full("scheduler", resolved, payload,
                                       NULL, msg_type ? msg_type : "request", NULL,
                                       0, DEFAULT_MAX_ATTEMPTS);
    if (!msg) {
        LOG_ERROR("sched_send_callback: failed to create message for %s", to);
        return;
    }

    msgqueue_send(&g_msgqueue, resolved, msg);
    LOG_INFO("Scheduled send: scheduler -> %s, msg_id=%s", resolved, msg->msg_id);

    // Wake-up notification for MCP servers
    {
        json_t *evt = json_object();
        json_object_set_new(evt, "event", json_string("ipc_message"));
        json_object_set_new(evt, "msg_id", json_string(msg->msg_id));
        json_object_set_new(evt, "to", json_string(resolved));
        json_object_set_new(evt, "from", json_string("scheduler"));
        json_object_set_new(evt, "ts", json_integer((json_int_t)msg->ts));
        char *evt_s = json_dumps(evt, JSON_COMPACT);
        if (evt_s) {
            char linebuf[2048];
            snprintf(linebuf, sizeof(linebuf), "%s\n", evt_s);
            notify_broadcast_line(linebuf);
            free(evt_s);
        }
        json_decref(evt);
    }

    // Push notification via tmux or pty
    if (target) {
        notify_agent(target, "scheduler", msg->msg_id);
    }
}

// ============ Delayed Queue Delivery Callback ============

static void delayed_deliver_callback(const char *to, const char *msg_id, const char *from, const Message *msg) {
    LOG_INFO("Delayed deliver: %s -> %s, msg_id=%s", from ? from : "unknown", to, msg_id);

    // Resolve target for tmux_pane lookup
    char resolved[MAX_INSTANCE_ID];
    Agent *target = NULL;
    char error_msg[256] = {0};

    if (resolve_target(&g_registry, to, resolved, sizeof(resolved), &target, error_msg, sizeof(error_msg)) != 0) {
        strncpy(resolved, to, sizeof(resolved) - 1);
    }

    // Wake-up notification for MCP servers
    {
        json_t *evt = json_object();
        json_object_set_new(evt, "event", json_string("ipc_message"));
        json_object_set_new(evt, "msg_id", json_string(msg_id));
        json_object_set_new(evt, "to", json_string(resolved));
        json_object_set_new(evt, "to_raw", json_string(to));
        json_object_set_new(evt, "from", json_string(from ? from : "delayed"));
        json_object_set_new(evt, "ts", json_integer((json_int_t)msg->ts));
        char *evt_s = json_dumps(evt, JSON_COMPACT);
        if (evt_s) {
            char linebuf[2048];
            snprintf(linebuf, sizeof(linebuf), "%s\n", evt_s);
            notify_broadcast_line(linebuf);
            free(evt_s);
        }
        json_decref(evt);
    }

    // Push notification via tmux or pty
    if (target && (target->tmux_pane[0] || target->pty_path[0])) {
        LOG_INFO("Delayed notify: pane=%s, pty=%s, from=%s, msg_id=%s",
                 target->tmux_pane, target->pty_path, from ? from : "delayed", msg_id);
        notify_agent(target, from ? from : "delayed", msg_id);
    } else {
        LOG_INFO("Delayed notify: SKIPPED (target=%p, pane=%s, pty=%s)",
                 (void*)target, target ? target->tmux_pane : "null", target ? target->pty_path : "null");
    }
}

// ============ IPC Handlers ============

static char* handle_ipc_send(json_t *data) {
    const char *from = json_string_value(json_object_get(data, "from"));
    const char *to = json_string_value(json_object_get(data, "to"));
    json_t *payload = json_object_get(data, "payload");
    const char *conv_id = json_string_value(json_object_get(data, "conversation_id"));
    const char *msg_type = json_string_value(json_object_get(data, "message_type"));
    const char *trace_id = json_string_value(json_object_get(data, "trace_id"));
    const char *client_msg_id = json_string_value(json_object_get(data, "msg_id"));
    int ttl_seconds = (int)json_integer_value(json_object_get(data, "ttl_seconds"));
    int max_attempts = (int)json_integer_value(json_object_get(data, "max_attempts"));

    if (!to || !to[0]) {
        return json_error("missing 'to' field");
    }

    // Resolve target
    char resolved[MAX_INSTANCE_ID];
    Agent *target = NULL;
    char error_msg[256] = {0};

    if (resolve_target(&g_registry, to, resolved, sizeof(resolved), &target, error_msg, sizeof(error_msg)) != 0) {
        if (error_msg[0]) {
            return json_error(error_msg);
        }
    }

    // Auto-heartbeat sender
    if (from && from[0]) {
        char parsed_name[MAX_AGENT_NAME], parsed_session[MAX_TMUX_SESSION], parsed_pane[MAX_TMUX_PANE];
        parse_instance_id(from, parsed_name, sizeof(parsed_name),
                         parsed_session, sizeof(parsed_session), parsed_pane, sizeof(parsed_pane));
        registry_heartbeat_full(&g_registry, parsed_name[0] ? parsed_name : from, parsed_session, parsed_pane);
    }

    // Convert payload to string
    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");

    // Use client-provided msg_id if available, otherwise generate new one
    Message *msg = message_create_with_id(client_msg_id, from ? from : "unknown", resolved, payload_str,
                                          conv_id, msg_type ? msg_type : "request", trace_id,
                                          ttl_seconds, max_attempts > 0 ? max_attempts : DEFAULT_MAX_ATTEMPTS);
    free(payload_str);

    if (!msg) {
        return json_error("failed to create message");
    }

    msgqueue_send(&g_msgqueue, resolved, msg);
    LOG_INFO("IPC send: %s -> %s, msg_id=%s", from ? from : "unknown", resolved, msg->msg_id);

    // Wake-up notification for MCP servers (payload-free; agent should call ipc_recv)
    {
        json_t *evt = json_object();
        json_object_set_new(evt, "event", json_string("ipc_message"));
        json_object_set_new(evt, "msg_id", json_string(msg->msg_id));
        json_object_set_new(evt, "to", json_string(resolved));
        json_object_set_new(evt, "to_raw", json_string(to));
        json_object_set_new(evt, "from", json_string(from ? from : "unknown"));
        if (conv_id && conv_id[0]) {
            json_object_set_new(evt, "conversation_id", json_string(conv_id));
        } else {
            json_object_set_new(evt, "conversation_id", json_null());
        }
        json_object_set_new(evt, "ts", json_integer((json_int_t)msg->ts));
        char *evt_s = json_dumps(evt, JSON_COMPACT);
        if (evt_s) {
            char linebuf[2048];
            snprintf(linebuf, sizeof(linebuf), "%s\n", evt_s);
            notify_broadcast_line(linebuf);
            free(evt_s);
        }
        json_decref(evt);
    }

    // Push notification via tmux or pty (optional)
    if (g_tmux_notify_enabled && target && (target->tmux_pane[0] || target->pty_path[0])) {
        notify_agent(target, from, msg->msg_id);
        LOG_INFO("Notify agent: pane=%s pty=%s", target->tmux_pane, target->pty_path);
    }

    // Update conversation activity
    if (conv_id && conv_id[0]) {
        conversation_update_activity(&g_conversation_manager, conv_id);
    }

    char extra[512];
    snprintf(extra, sizeof(extra),
             "\"msg_id\":\"%s\",\"to\":\"%s\",\"conversation_id\":%s%s%s,\"queued_at\":%ld",
             msg->msg_id, resolved,
             conv_id ? "\"" : "", conv_id ? conv_id : "null", conv_id ? "\"" : "",
             (long)msg->ts);
    return json_ok(extra);
}

static char* handle_ipc_recv(json_t *data) {
    const char *agent = json_string_value(json_object_get(data, "agent"));
    const char *conv_id = json_string_value(json_object_get(data, "conversation_id"));

    if (!agent || !agent[0]) {
        return json_error("missing 'agent' field");
    }

    // Auto-heartbeat receiver
    char parsed_name[MAX_AGENT_NAME], parsed_session[MAX_TMUX_SESSION], parsed_pane[MAX_TMUX_PANE];
    parse_instance_id(agent, parsed_name, sizeof(parsed_name),
                     parsed_session, sizeof(parsed_session), parsed_pane, sizeof(parsed_pane));
    registry_heartbeat_full(&g_registry, parsed_name[0] ? parsed_name : agent, parsed_session, parsed_pane);

    // Resolve target to find correct queue (handles same-pane merging)
    char resolved[MAX_INSTANCE_ID];
    char error_buf[256];
    if (resolve_target(&g_registry, agent, resolved, sizeof(resolved), NULL, error_buf, sizeof(error_buf)) != 0) {
        strncpy(resolved, agent, sizeof(resolved) - 1);
    }

    // Build response
    char *buf = malloc(BUFFER_SIZE);
    size_t offset = 0;
    int count = 0;

    offset += snprintf(buf + offset, BUFFER_SIZE - offset,
                       "{\"status\":\"ok\",\"messages\":[");

    // Determine logical name for fallback queue lookup.
    const char *logical_name = parsed_name[0] ? parsed_name : agent;
    int need_fallback = (strcmp(resolved, logical_name) != 0);

    // Consume messages immediately (recv = ack)
    Message *msgs = conv_id && conv_id[0] ?
        msgqueue_recv_filtered(&g_msgqueue, resolved, conv_id) :
        msgqueue_recv(&g_msgqueue, resolved);

    // Fallback: also check logical name queue (offline-queued messages)
    if (!msgs && need_fallback) {
        msgs = conv_id && conv_id[0] ?
            msgqueue_recv_filtered(&g_msgqueue, logical_name, conv_id) :
            msgqueue_recv(&g_msgqueue, logical_name);
        if (msgs) {
            LOG_INFO("IPC recv fallback: %s consuming from logical queue '%s'",
                     agent, logical_name);
        }
    }

    Message *m = msgs;
    while (m && offset < BUFFER_SIZE - 1000) {
        char *msg_json = message_to_json(m);
        if (count > 0) {
            offset += snprintf(buf + offset, BUFFER_SIZE - offset, ",");
        }
        offset += snprintf(buf + offset, BUFFER_SIZE - offset, "%s", msg_json);
        free(msg_json);

        if (m->conversation_id) {
            conversation_update_activity(&g_conversation_manager, m->conversation_id);
        }

        Message *next = m->next;
        message_free(m);
        m = next;
        count++;
    }

    snprintf(buf + offset, BUFFER_SIZE - offset,
             "],\"count\":%d}\n", count);

    if (count > 0) {
        LOG_INFO("IPC recv: %s received %d messages", agent, count);
    }
    return buf;
}

static char* handle_ipc_ack(json_t *data) {
    const char *agent = json_string_value(json_object_get(data, "agent"));
    json_t *msg_ids_arr = json_object_get(data, "msg_ids");

    if (!agent || !agent[0]) {
        return json_error("missing 'agent' field");
    }

    if (!json_is_array(msg_ids_arr) || json_array_size(msg_ids_arr) == 0) {
        return json_error("msg_ids must be a non-empty array");
    }

    // Extract msg_ids
    int id_count = (int)json_array_size(msg_ids_arr);
    const char **msg_ids = malloc(id_count * sizeof(char*));
    for (int i = 0; i < id_count; i++) {
        msg_ids[i] = json_string_value(json_array_get(msg_ids_arr, i));
    }

    // Auto-heartbeat
    char parsed_name[MAX_AGENT_NAME], parsed_session[MAX_TMUX_SESSION], parsed_pane[MAX_TMUX_PANE];
    parse_instance_id(agent, parsed_name, sizeof(parsed_name),
                     parsed_session, sizeof(parsed_session), parsed_pane, sizeof(parsed_pane));
    registry_heartbeat_full(&g_registry, parsed_name[0] ? parsed_name : agent, parsed_session, parsed_pane);

    // Resolve to find correct queue key
    char resolved[MAX_INSTANCE_ID];
    char resolve_err[256];
    if (resolve_target(&g_registry, agent, resolved, sizeof(resolved), NULL, resolve_err, sizeof(resolve_err)) != 0) {
        strncpy(resolved, agent, sizeof(resolved) - 1);
    }

    // Perform ACK on resolved queue
    int acked = 0;
    char missing_buf[4096] = {0};
    msgqueue_ack(&g_msgqueue, resolved, msg_ids, id_count, &acked, missing_buf, sizeof(missing_buf));

    // Fallback: if some messages missing, try logical name queue
    // (messages claimed via fallback in ipc_recv have inflight records under logical name)
    const char *logical_name = parsed_name[0] ? parsed_name : agent;
    if (acked < id_count && strcmp(resolved, logical_name) != 0) {
        int fallback_acked = 0;
        char fallback_missing[4096] = {0};
        msgqueue_ack(&g_msgqueue, logical_name, msg_ids, id_count, &fallback_acked, fallback_missing, sizeof(fallback_missing));
        if (fallback_acked > 0) {
            acked += fallback_acked;
            LOG_INFO("IPC ack fallback: %s acked %d more from logical queue '%s'",
                     agent, fallback_acked, logical_name);
            // Rebuild missing list from fallback result
            if (acked >= id_count) {
                missing_buf[0] = '\0';
            } else {
                strncpy(missing_buf, fallback_missing, sizeof(missing_buf) - 1);
            }
        }
    }

    free(msg_ids);

    LOG_INFO("IPC ack: %s acked %d messages", agent, acked);

    char extra[8192];
    snprintf(extra, sizeof(extra), "\"acked\":%d,\"missing\":[%s]", acked, missing_buf);
    return json_ok(extra);
}

static char* handle_ipc_send_delayed(json_t *data) {
    const char *from = json_string_value(json_object_get(data, "from"));
    const char *to = json_string_value(json_object_get(data, "to"));
    json_t *payload = json_object_get(data, "payload");
    const char *conv_id = json_string_value(json_object_get(data, "conversation_id"));
    const char *msg_type = json_string_value(json_object_get(data, "message_type"));
    int delay_seconds = (int)json_integer_value(json_object_get(data, "delay_seconds"));
    int ttl_seconds = (int)json_integer_value(json_object_get(data, "ttl_seconds"));
    int max_attempts = (int)json_integer_value(json_object_get(data, "max_attempts"));

    if (!to || !to[0]) {
        return json_error("missing 'to' field");
    }
    if (delay_seconds < 1 || delay_seconds > 86400) {
        return json_error("delay_seconds must be 1-86400");
    }

    // Resolve target now so delayed delivery uses the same queue key as ipc_recv
    char resolved_to[MAX_INSTANCE_ID];
    char err_buf[256] = {0};
    if (resolve_target(&g_registry, to, resolved_to, sizeof(resolved_to), NULL, err_buf, sizeof(err_buf)) != 0) {
        // Fallback to plain name if resolution fails (agent may register later)
        strncpy(resolved_to, to, sizeof(resolved_to) - 1);
        resolved_to[sizeof(resolved_to) - 1] = '\0';
    }

    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");

    Message *msg = message_create_full(from ? from : "unknown", resolved_to, payload_str,
                                       conv_id, msg_type ? msg_type : "response", NULL,
                                       ttl_seconds, max_attempts > 0 ? max_attempts : DEFAULT_MAX_ATTEMPTS);
    free(payload_str);

    if (!msg) {
        return json_error("failed to create message");
    }

    time_t send_at = delayed_queue_schedule(&g_delayed_queue, msg, delay_seconds);
    if (send_at == 0) {
        message_free(msg);
        return json_error("failed to schedule delayed message");
    }

    LOG_INFO("IPC delayed send: %s -> %s (resolved: %s), delay=%ds, msg_id=%s", from ? from : "unknown", to, resolved_to, delay_seconds, msg->msg_id);

    char extra[512];
    snprintf(extra, sizeof(extra),
             "\"status\":\"scheduled\",\"msg_id\":\"%s\",\"conversation_id\":%s%s%s,\"send_at\":%ld",
             msg->msg_id,
             conv_id ? "\"" : "", conv_id ? conv_id : "null", conv_id ? "\"" : "",
             (long)send_at);

    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE, "{%s}\n", extra);
    return buf;
}

static char* handle_conversation_create(json_t *data) {
    json_t *participants_obj = json_object_get(data, "participants");
    json_t *metadata_obj = json_object_get(data, "metadata");
    char *metadata = metadata_obj ? json_dumps(metadata_obj, JSON_COMPACT) : NULL;
    char participants[1024] = {0};

    // Accept both string "a,b" and array ["a", "b"] formats
    if (json_is_string(participants_obj)) {
        strncpy(participants, json_string_value(participants_obj), sizeof(participants) - 1);
    } else if (json_is_array(participants_obj)) {
        size_t idx;
        json_t *val;
        int offset = 0;
        json_array_foreach(participants_obj, idx, val) {
            const char *p = json_string_value(val);
            if (p && offset < (int)sizeof(participants) - 64) {
                if (idx > 0) participants[offset++] = ',';
                offset += snprintf(participants + offset, sizeof(participants) - offset, "%s", p);
            }
        }
    }

    if (!participants[0]) {
        if (metadata) free(metadata);
        return json_error("missing 'participants' field");
    }

    char conv_id[MAX_CONVERSATION_ID];
    if (!conversation_create(&g_conversation_manager, participants, metadata, conv_id, sizeof(conv_id))) {
        if (metadata) free(metadata);
        return json_error("failed to create conversation (need at least 2 participants)");
    }

    if (metadata) free(metadata);

    LOG_INFO("Conversation created: %s (participants=%s)", conv_id, participants);

    char extra[512];
    snprintf(extra, sizeof(extra), "\"conversation_id\":\"%s\",\"participants\":\"%s\"",
             conv_id, participants);
    return json_ok(extra);
}

static char* handle_ipc_status(json_t *data) {
    (void)data;

    char mq_stats[4096];
    char dq_stats[1024];
    char conv_stats[1024];
    char reg_stats[1024];

    msgqueue_stats(&g_msgqueue, mq_stats, sizeof(mq_stats));
    delayed_queue_stats(&g_delayed_queue, dq_stats, sizeof(dq_stats));
    conversation_stats(&g_conversation_manager, conv_stats, sizeof(conv_stats));
    registry_stats(&g_registry, reg_stats, sizeof(reg_stats));

    char *sched_stats_str = sched_stats(&g_scheduled_queue);

    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE,
             "{\"status\":\"ok\",\"stats\":{"
             "\"msgqueue\":%s,"
             "\"delayed_queue\":%s,"
             "\"conversations\":%s,"
             "\"registry\":%s,"
             "\"scheduler\":%s"
             "}}\n",
             mq_stats, dq_stats, conv_stats, reg_stats,
             sched_stats_str ? sched_stats_str : "{}");

    if (sched_stats_str) free(sched_stats_str);
    return buf;
}

// ============ Business Handlers ============

static char* handle_audit_log(json_t *data) {
    const char *tool_name = json_string_value(json_object_get(data, "tool_name"));
    // Simple implementation: just acknowledge
    // Full implementation would call external audit_log.py or write to file
    if (!tool_name || !tool_name[0]) {
        return json_ok("\"logged\":false,\"reason\":\"no tool_name\"");
    }
    LOG_INFO("Audit log: tool=%s", tool_name);
    return json_ok("\"logged\":true");
}

static char* handle_lep_check(json_t *data) {
    (void)data;
    // Simple implementation: always pass
    // Full implementation would call external lep_engine.py
    return json_ok("\"decision\":\"pass\"");
}

static char* handle_pre_write_check(json_t *data) {
    const char *file_path = json_string_value(json_object_get(data, "file_path"));

    if (!file_path || !file_path[0]) {
        return json_ok("\"decision\":\"pass\"");
    }

    // Check protected paths
    const char *protected[] = {
        "/brain/base/spec/core/",
        "/brain/base/spec/schema/",
        NULL
    };

    for (int i = 0; protected[i]; i++) {
        if (strncmp(file_path, protected[i], strlen(protected[i])) == 0) {
            char *buf = malloc(BUFFER_SIZE);
            snprintf(buf, BUFFER_SIZE,
                     "{\"status\":\"block\",\"decision\":\"block\",\"reason\":\"Protected path: %s\"}\n",
                     protected[i]);
            return buf;
        }
    }

    return json_ok("\"decision\":\"pass\"");
}

static char* handle_pre_bash_check(json_t *data) {
    const char *command = json_string_value(json_object_get(data, "command"));

    if (!command || !command[0]) {
        return json_ok("\"decision\":\"pass\"");
    }

    // Detect delete commands
    const char *delete_patterns[] = {"rm ", "rm -", "rmdir ", "unlink ", NULL};
    int is_delete = 0;
    for (int i = 0; delete_patterns[i]; i++) {
        if (strstr(command, delete_patterns[i])) {
            is_delete = 1;
            break;
        }
    }

    if (is_delete) {
        return json_ok("\"decision\":\"pass\",\"warning\":\"G-DELETE-BACKUP: Ensure backup before delete\"");
    }

    return json_ok("\"decision\":\"pass\"");
}

static char* handle_rag_query(json_t *data) {
    (void)data;
    // Placeholder
    return json_ok("\"results\":[],\"message\":\"RAG not implemented yet\"");
}

static char* handle_register_tmux_logger(json_t *data) {
    const char *pane = json_string_value(json_object_get(data, "pane"));
    const char *output_file = json_string_value(json_object_get(data, "output_file"));

    if (!pane || !pane[0] || !output_file || !output_file[0]) {
        return json_error("missing pane or output_file");
    }

    // Placeholder - would start tmux logger subprocess
    LOG_INFO("Register tmux logger: pane=%s, output=%s", pane, output_file);
    return json_ok("\"registered\":true");
}

// ============ Schedule Handlers ============

static char* handle_ipc_schedule_cron(json_t *data) {
    const char *task_id = json_string_value(json_object_get(data, "task_id"));
    const char *cron_expr = json_string_value(json_object_get(data, "cron_expr"));
    const char *to = json_string_value(json_object_get(data, "to"));
    json_t *payload = json_object_get(data, "payload");
    const char *msg_type = json_string_value(json_object_get(data, "message_type"));
    int max_runs = (int)json_integer_value(json_object_get(data, "max_runs"));

    if (!task_id || !task_id[0]) {
        return json_error("missing task_id");
    }
    if (!cron_expr || !cron_expr[0]) {
        return json_error("missing cron_expr");
    }
    if (!to || !to[0]) {
        return json_error("missing 'to' field");
    }

    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");

    int ret = sched_add_cron(&g_scheduled_queue, task_id, cron_expr,
                             to, payload_str, msg_type, max_runs);
    free(payload_str);

    if (ret == -1) {
        return json_error("task_id already exists");
    } else if (ret == -2) {
        return json_error("scheduler full (max 256 tasks)");
    } else if (ret == -3) {
        return json_error("invalid cron expression");
    }

    LOG_INFO("Schedule cron: %s (%s) -> %s", task_id, cron_expr, to);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"task_id\":\"%s\",\"task_type\":\"cron\",\"cron_expr\":\"%s\"",
             task_id, cron_expr);
    return json_ok(extra);
}

static char* handle_ipc_schedule_periodic(json_t *data) {
    const char *task_id = json_string_value(json_object_get(data, "task_id"));
    int interval = (int)json_integer_value(json_object_get(data, "interval_seconds"));
    const char *to = json_string_value(json_object_get(data, "to"));
    json_t *payload = json_object_get(data, "payload");
    const char *msg_type = json_string_value(json_object_get(data, "message_type"));
    int max_runs = (int)json_integer_value(json_object_get(data, "max_runs"));
    json_t *run_imm = json_object_get(data, "run_immediately");
    bool run_immediately = run_imm && json_is_true(run_imm);

    if (!task_id || !task_id[0]) {
        return json_error("missing task_id");
    }
    if (interval < 1) {
        return json_error("interval_seconds must be >= 1");
    }
    if (!to || !to[0]) {
        return json_error("missing 'to' field");
    }

    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");

    int ret = sched_add_periodic(&g_scheduled_queue, task_id, interval,
                                 to, payload_str, msg_type, max_runs, run_immediately);
    free(payload_str);

    if (ret == -1) {
        return json_error("task_id already exists");
    } else if (ret == -2) {
        return json_error("scheduler full (max 256 tasks)");
    }

    LOG_INFO("Schedule periodic: %s (every %ds) -> %s", task_id, interval, to);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"task_id\":\"%s\",\"task_type\":\"periodic\",\"interval_seconds\":%d",
             task_id, interval);
    return json_ok(extra);
}

static char* handle_ipc_schedule_once(json_t *data) {
    const char *task_id = json_string_value(json_object_get(data, "task_id"));
    json_int_t run_at = json_integer_value(json_object_get(data, "run_at"));
    int delay = (int)json_integer_value(json_object_get(data, "delay_seconds"));
    const char *to = json_string_value(json_object_get(data, "to"));
    json_t *payload = json_object_get(data, "payload");
    const char *msg_type = json_string_value(json_object_get(data, "message_type"));

    if (!task_id || !task_id[0]) {
        return json_error("missing task_id");
    }
    if (!to || !to[0]) {
        return json_error("missing 'to' field");
    }

    time_t actual_run_at;
    if (run_at > 0) {
        actual_run_at = (time_t)run_at;
    } else if (delay > 0) {
        actual_run_at = time(NULL) + delay;
    } else {
        return json_error("must specify run_at or delay_seconds");
    }

    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");

    int ret = sched_add_once(&g_scheduled_queue, task_id, actual_run_at,
                             to, payload_str, msg_type);
    free(payload_str);

    if (ret == -1) {
        return json_error("task_id already exists");
    } else if (ret == -2) {
        return json_error("scheduler full (max 256 tasks)");
    }

    LOG_INFO("Schedule once: %s (at %ld) -> %s", task_id, (long)actual_run_at, to);

    char extra[256];
    snprintf(extra, sizeof(extra), "\"task_id\":\"%s\",\"task_type\":\"once\",\"run_at\":%ld",
             task_id, (long)actual_run_at);
    return json_ok(extra);
}

static char* handle_ipc_schedule_remove(json_t *data) {
    const char *task_id = json_string_value(json_object_get(data, "task_id"));

    if (!task_id || !task_id[0]) {
        return json_error("missing task_id");
    }

    int ret = sched_remove(&g_scheduled_queue, task_id);
    if (ret != 0) {
        return json_error("task not found");
    }

    LOG_INFO("Schedule remove: %s", task_id);

    char extra[128];
    snprintf(extra, sizeof(extra), "\"task_id\":\"%s\",\"removed\":true", task_id);
    return json_ok(extra);
}

static char* handle_ipc_schedule_enable(json_t *data) {
    const char *task_id = json_string_value(json_object_get(data, "task_id"));
    json_t *enabled_val = json_object_get(data, "enabled");

    if (!task_id || !task_id[0]) {
        return json_error("missing task_id");
    }

    bool enabled = true;
    if (enabled_val && json_is_false(enabled_val)) {
        enabled = false;
    }

    int ret = sched_enable(&g_scheduled_queue, task_id, enabled);
    if (ret != 0) {
        return json_error("task not found");
    }

    LOG_INFO("Schedule %s: %s", enabled ? "enable" : "disable", task_id);

    char extra[128];
    snprintf(extra, sizeof(extra), "\"task_id\":\"%s\",\"enabled\":%s",
             task_id, enabled ? "true" : "false");
    return json_ok(extra);
}

static char* handle_ipc_schedule_list(json_t *data) {
    (void)data;

    char *tasks_json = sched_list_tasks(&g_scheduled_queue);
    if (!tasks_json) {
        return json_error("failed to list tasks");
    }

    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE, "{\"status\":\"ok\",\"tasks\":%s}\n", tasks_json);
    free(tasks_json);

    return buf;
}

static char* handle_ipc_schedule_stats(json_t *data) {
    (void)data;

    char *stats_json = sched_stats(&g_scheduled_queue);
    if (!stats_json) {
        return json_error("failed to get stats");
    }

    char *buf = malloc(BUFFER_SIZE);
    snprintf(buf, BUFFER_SIZE, "{\"status\":\"ok\",\"scheduler\":%s}\n", stats_json);
    free(stats_json);

    return buf;
}

// ============ Request Dispatcher ============

static char* handle_request(const char *req_str, int client_fd) {
    json_error_t error;
    json_t *root = json_loads(req_str, 0, &error);

    if (!root) {
        return json_error("invalid JSON");
    }

    const char *action = json_string_value(json_object_get(root, "action"));
    json_t *data = json_object_get(root, "data");

    char *response = NULL;

    if (!action) {
        response = json_error("missing action");
    } else if (strcmp(action, "ping") == 0) {
        response = handle_ping(data);
    } else if (strcmp(action, "agent_register") == 0) {
        response = handle_agent_register(data);
    } else if (strcmp(action, "agent_heartbeat") == 0) {
        response = handle_agent_heartbeat(data);
    } else if (strcmp(action, "agent_list") == 0) {
        response = handle_agent_list(data);
    } else if (strcmp(action, "agent_unregister") == 0) {
        response = handle_agent_unregister(data);
    } else if (strcmp(action, "service_register") == 0) {
        response = handle_service_register(data, client_fd);
    } else if (strcmp(action, "service_heartbeat") == 0) {
        response = handle_service_heartbeat(data);
    } else if (strcmp(action, "ipc_send") == 0) {
        response = handle_ipc_send(data);
    } else if (strcmp(action, "ipc_recv") == 0) {
        response = handle_ipc_recv(data);
    } else if (strcmp(action, "ipc_ack") == 0) {
        response = handle_ipc_ack(data);
    } else if (strcmp(action, "ipc_send_delayed") == 0) {
        response = handle_ipc_send_delayed(data);
    } else if (strcmp(action, "conversation_create") == 0) {
        response = handle_conversation_create(data);
    } else if (strcmp(action, "ipc_status") == 0) {
        response = handle_ipc_status(data);
    } else if (strcmp(action, "audit_log") == 0) {
        response = handle_audit_log(data);
    } else if (strcmp(action, "lep_check") == 0) {
        response = handle_lep_check(data);
    } else if (strcmp(action, "pre_write_check") == 0) {
        response = handle_pre_write_check(data);
    } else if (strcmp(action, "pre_bash_check") == 0) {
        response = handle_pre_bash_check(data);
    } else if (strcmp(action, "rag_query") == 0) {
        response = handle_rag_query(data);
    } else if (strcmp(action, "register_tmux_logger") == 0) {
        response = handle_register_tmux_logger(data);
    } else if (strcmp(action, "ipc_schedule_cron") == 0) {
        response = handle_ipc_schedule_cron(data);
    } else if (strcmp(action, "ipc_schedule_periodic") == 0) {
        response = handle_ipc_schedule_periodic(data);
    } else if (strcmp(action, "ipc_schedule_once") == 0) {
        response = handle_ipc_schedule_once(data);
    } else if (strcmp(action, "ipc_schedule_remove") == 0) {
        response = handle_ipc_schedule_remove(data);
    } else if (strcmp(action, "ipc_schedule_enable") == 0) {
        response = handle_ipc_schedule_enable(data);
    } else if (strcmp(action, "ipc_schedule_list") == 0) {
        response = handle_ipc_schedule_list(data);
    } else if (strcmp(action, "ipc_schedule_stats") == 0) {
        response = handle_ipc_schedule_stats(data);
    } else {
        char errmsg[128];
        snprintf(errmsg, sizeof(errmsg), "unknown action: %s", action);
        response = json_error(errmsg);
    }

    json_decref(root);
    return response;
}

// ============ Client Handler ============

static void* client_thread(void *arg) {
    int fd = *(int*)arg;
    free(arg);

    char buffer[BUFFER_SIZE];
    ssize_t n = recv(fd, buffer, sizeof(buffer) - 1, 0);

    if (n > 0) {
        buffer[n] = '\0';
        char *nl = strchr(buffer, '\n');
        if (nl) *nl = '\0';

        char *response = handle_request(buffer, fd);
        if (response) {
            send(fd, response, strlen(response), 0);
            free(response);
        }
    }

    close(fd);
    return NULL;
}

// ============ Background Threads ============

static void* retry_thread(void *arg) {
    (void)arg;
    LOG_INFO("Retry thread started");

    while (!g_shutdown) {
        msgqueue_retry_tick(&g_msgqueue);
        sleep(1);
    }

    LOG_INFO("Retry thread stopped");
    return NULL;
}

static void* delayed_thread(void *arg) {
    (void)arg;
    LOG_INFO("Delayed queue thread started");

    while (!g_shutdown) {
        delayed_queue_tick(&g_delayed_queue);
        sleep(1);
    }

    LOG_INFO("Delayed queue thread stopped");
    return NULL;
}

static const char* derive_agent_name_from_session(const char *session_name) {
    if (!session_name || !session_name[0]) return NULL;

    /*
     * Sandbox tmux sessions use:
     *   sbx_<instance_id>__<logical_agent_name>
     * Discovery must recover the logical agent name so IPC routing by
     * agent_name resolves to the pane-backed sandbox instance instead of a
     * synthetic sbx_* alias.
     */
    const char *logical = strstr(session_name, "__");
    if (logical && logical[2]) {
        logical += 2;
    } else {
        logical = session_name;
    }

    static char name_buf[MAX_AGENT_NAME];
    strncpy(name_buf, logical, sizeof(name_buf) - 1);
    name_buf[sizeof(name_buf) - 1] = '\0';

    // Handle legacy alias: codex-cli -> codex
    if (strcmp(name_buf, "codex-cli") == 0) {
        return "codex";
    }

    return name_buf;
}

static void* tmux_discovery_thread(void *arg) {
    (void)arg;
    LOG_INFO("Tmux discovery thread started");

    while (!g_shutdown) {
        // Snapshot all panes, then prune registry entries whose pane no longer exists.
        // This prevents stale/ghost agents from accumulating and also enforces
        // the "one pane -> one agent" invariant in practice.
        enum { MAX_TMUX_PANES_SNAPSHOT = 1024 };
        char seen_panes[MAX_TMUX_PANES_SNAPSHOT][MAX_TMUX_PANE];
        int seen_count = 0;

        // Run tmux list-panes
        FILE *fp = popen("tmux list-panes -a -F '#{pane_id}\t#{session_name}\t#{pane_pid}\t#{pane_current_command}' 2>/dev/null", "r");
        if (fp) {
            char line[512];
            while (fgets(line, sizeof(line), fp)) {
                // Remove newline
                char *nl = strchr(line, '\n');
                if (nl) *nl = '\0';

                // Parse: pane_id\tsession_name\tpid\tcommand
                char *pane_id = strtok(line, "\t");
                char *session_name = strtok(NULL, "\t");

                if (pane_id && session_name) {
                    // Record pane_id for pruning (all sessions, not only known prefixes)
                    if (seen_count < MAX_TMUX_PANES_SNAPSHOT) {
                        bool already = false;
                        for (int i = 0; i < seen_count; i++) {
                            if (strcmp(seen_panes[i], pane_id) == 0) {
                                already = true;
                                break;
                            }
                        }
                        if (!already) {
                            strncpy(seen_panes[seen_count], pane_id, MAX_TMUX_PANE - 1);
                            seen_panes[seen_count][MAX_TMUX_PANE - 1] = '\0';
                            seen_count++;
                        }
                    }

                    const char *agent_name = derive_agent_name_from_session(session_name);
                    if (agent_name) {
                        registry_update_from_tmux(&g_registry, pane_id, session_name, agent_name);
                    }
                }
            }
            pclose(fp);

            // Prune after a successful snapshot
            const char *pane_ptrs[MAX_TMUX_PANES_SNAPSHOT];
            for (int i = 0; i < seen_count; i++) pane_ptrs[i] = seen_panes[i];
            int removed = registry_prune_missing_panes(&g_registry, pane_ptrs, seen_count);
            if (removed > 0) {
                LOG_INFO("Pruned %d stale agents (tmux pane missing)", removed);
            }
        }

        sleep(TMUX_DISCOVERY_INTERVAL);
    }

    LOG_INFO("Tmux discovery thread stopped");
    return NULL;
}

static void* conversation_cleanup_thread(void *arg) {
    (void)arg;
    LOG_INFO("Conversation cleanup thread started");

    while (!g_shutdown) {
        sleep(3600); // Run every hour
        if (!g_shutdown) {
            int cleaned = conversation_cleanup_stale(&g_conversation_manager);
            if (cleaned > 0) {
                LOG_INFO("Cleaned up %d stale conversations", cleaned);
            }
        }
    }

    LOG_INFO("Conversation cleanup thread stopped");
    return NULL;
}

// ============ PID File ============

static void write_pid(void) {
    FILE *f = fopen(PID_FILE, "w");
    if (f) {
        fprintf(f, "%d", getpid());
        fclose(f);
    }
}

static void cleanup(void) {
    unlink(SOCKET_PATH);
    unlink(PID_FILE);
}

static int is_running(void) {
    FILE *f = fopen(PID_FILE, "r");
    if (!f) return 0;

    int pid;
    if (fscanf(f, "%d", &pid) == 1) {
        fclose(f);
        if (kill(pid, 0) == 0) {
            return 1;
        }
    } else {
        fclose(f);
    }
    return 0;
}

// ============ Main Server ============

static int run_server(void) {
    if (is_running()) {
        fprintf(stderr, "Brain IPC already running\n");
        return 1;
    }

    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);
    signal(SIGPIPE, SIG_IGN);
    signal(SIGCHLD, SIG_IGN); // Prevent zombie processes from tmux_notify

    cleanup();

    // Open log file (env override + sensible default).
    const char *log_path = getenv("BRAIN_DAEMON_LOG");
    if (!log_path || !log_path[0]) {
        log_path = LOG_FILE_DEFAULT;
    }
    ensure_parent_dir(log_path);
    g_logfile = fopen(log_path, "a");
    if (!g_logfile) {
        g_logfile = stderr;
    }

    g_start_time = time(NULL);
    g_tmux_notify_enabled = env_bool("BRAIN_TMUX_NOTIFY", 1);
    LOG_INFO("tmux_notify_enabled=%d (set BRAIN_TMUX_NOTIFY=0 to disable)", g_tmux_notify_enabled);

    // Initialize components
    msgqueue_init(&g_msgqueue);
    registry_init(&g_registry);
    registry_register_full(&g_registry, SELF_SERVICE_NAME, NULL, NULL, NULL, AGENT_SOURCE_SERVICE);
    delayed_queue_init(&g_delayed_queue, &g_msgqueue);
    delayed_queue_set_deliver_cb(&g_delayed_queue, delayed_deliver_callback);
    conversation_manager_init(&g_conversation_manager);
    if (sched_init(&g_scheduled_queue, sched_send_callback) != 0) {
        LOG_ERROR("Failed to initialize scheduled queue");
    } else {
        LOG_INFO("Scheduled queue initialized");
    }

    // Start brain_ipc notify socket for MCP wake-up
    notify_server_start();

    // Create socket
    int server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) {
        LOG_ERROR("socket() failed: %s", strerror(errno));
        return 1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        LOG_ERROR("bind() failed: %s", strerror(errno));
        close(server_fd);
        return 1;
    }

    chmod(SOCKET_PATH, 0666);

    if (listen(server_fd, MAX_CLIENTS) < 0) {
        LOG_ERROR("listen() failed: %s", strerror(errno));
        close(server_fd);
        return 1;
    }

    write_pid();

    // Start background threads
    pthread_t retry_tid, delayed_tid, discovery_tid, cleanup_tid;

    pthread_create(&retry_tid, NULL, retry_thread, NULL);
    pthread_create(&delayed_tid, NULL, delayed_thread, NULL);
    pthread_create(&discovery_tid, NULL, tmux_discovery_thread, NULL);
    pthread_create(&cleanup_tid, NULL, conversation_cleanup_thread, NULL);

    LOG_INFO("Brain IPC v2.0 started (C implementation, full feature parity)");
    printf("Brain IPC v2.0 running on %s (PID: %d)\n", SOCKET_PATH, getpid());

    // Self heartbeat using timestamp (update every 60 seconds)
    time_t last_heartbeat = time(NULL);
    int HEARTBEAT_INTERVAL = 60;

    // Accept loop
    while (!g_shutdown) {
        struct timeval tv = {1, 0};
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(server_fd, &fds);

        int ret = select(server_fd + 1, &fds, NULL, NULL, &tv);
        time_t now = time(NULL);

        // Check heartbeat on every loop iteration (not just timeout)
        if (now - last_heartbeat >= HEARTBEAT_INTERVAL) {
            registry_heartbeat(&g_registry, SELF_SERVICE_NAME);
            last_heartbeat = now;
        }

        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret == 0) {
            continue;
        }

        int client_fd = accept(server_fd, NULL, NULL);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            LOG_ERROR("accept() failed: %s", strerror(errno));
            continue;
        }

        int *fd_ptr = malloc(sizeof(int));
        *fd_ptr = client_fd;

        pthread_t tid;
        pthread_attr_t attr;
        pthread_attr_init(&attr);
        pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

        if (pthread_create(&tid, &attr, client_thread, fd_ptr) != 0) {
            LOG_ERROR("pthread_create() failed");
            close(client_fd);
            free(fd_ptr);
        }

        pthread_attr_destroy(&attr);
    }

    // Shutdown
    LOG_INFO("Shutting down...");

    sched_shutdown(&g_scheduled_queue);
    delayed_queue_shutdown(&g_delayed_queue);
    conversation_manager_shutdown(&g_conversation_manager);

    // Wait for threads (with timeout)
    pthread_join(retry_tid, NULL);
    pthread_join(delayed_tid, NULL);
    pthread_join(discovery_tid, NULL);

    notify_server_shutdown();

    close(server_fd);
    msgqueue_destroy(&g_msgqueue);
    registry_destroy(&g_registry);
    delayed_queue_destroy(&g_delayed_queue);
    conversation_manager_destroy(&g_conversation_manager);
    cleanup();

    LOG_INFO("Brain IPC v2.0 stopped");

    if (g_logfile && g_logfile != stderr) {
        fclose(g_logfile);
    }

    return 0;
}

// ============ Commands ============

static int cmd_status(void) {
    FILE *f = fopen(PID_FILE, "r");
    if (!f) {
        printf("Not running\n");
        return 1;
    }

    int pid;
    if (fscanf(f, "%d", &pid) == 1) {
        fclose(f);
        if (kill(pid, 0) == 0) {
            printf("Running (PID: %d)\n", pid);
            return 0;
        }
    } else {
        fclose(f);
    }
    printf("Not running\n");
    return 1;
}

static int cmd_stop(void) {
    FILE *f = fopen(PID_FILE, "r");
    if (!f) {
        printf("Not running\n");
        return 1;
    }

    int pid;
    if (fscanf(f, "%d", &pid) == 1) {
        fclose(f);
        if (kill(pid, SIGTERM) == 0) {
            printf("Sent SIGTERM to %d\n", pid);
            return 0;
        }
    } else {
        fclose(f);
    }
    printf("Not running\n");
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc > 1) {
        if (strcmp(argv[1], "status") == 0) {
            return cmd_status();
        } else if (strcmp(argv[1], "stop") == 0) {
            return cmd_stop();
        } else {
            fprintf(stderr, "Usage: %s [status|stop]\n", argv[0]);
            return 1;
        }
    }

    return run_server();
}
