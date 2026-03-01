#include "ipc_client.h"
#include "logger.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <jansson.h>

static char service_name[64] = {0};
static char socket_path[256] = {0};

int ipc_client_init(const char *name, const char *path) {
    strncpy(service_name, name, sizeof(service_name) - 1);
    strncpy(socket_path, path, sizeof(socket_path) - 1);
    log_info("IPC client initialized: service=%s, socket=%s", service_name, socket_path);
    return 0;
}

static int connect_socket(void) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        log_error("Failed to create socket: %s", strerror(errno));
        return -1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        log_error("Failed to connect to %s: %s", socket_path, strerror(errno));
        close(fd);
        return -1;
    }

    return fd;
}

static int read_line(int fd, char *out, size_t out_size) {
    size_t off = 0;
    while (off + 1 < out_size) {
        char c = '\0';
        ssize_t n = read(fd, &c, 1);
        if (n <= 0) break;
        out[off++] = c;
        if (c == '\n') break;
    }
    out[off] = '\0';
    return off > 0 ? 0 : -1;
}

static int daemon_request(const char *action, json_t *data, json_t **out_resp) {
    int fd = connect_socket();
    if (fd < 0) return -1;

    json_t *req = json_object();
    json_object_set_new(req, "action", json_string(action));
    json_object_set(req, "data", data ? data : json_object());

    char *line = json_dumps(req, JSON_COMPACT);
    json_decref(req);
    if (!line) {
        close(fd);
        return -1;
    }

    size_t len = strlen(line);
    char *buf = malloc(len + 2);
    memcpy(buf, line, len);
    buf[len] = '\n';
    buf[len + 1] = '\0';
    free(line);

    ssize_t off = 0;
    while (off < (ssize_t)(len + 1)) {
        ssize_t n = write(fd, buf + off, (size_t)(len + 1 - off));
        if (n < 0) {
            free(buf);
            close(fd);
            return -1;
        }
        off += n;
    }
    free(buf);

    char resp_buf[8192];
    if (read_line(fd, resp_buf, sizeof(resp_buf)) != 0) {
        close(fd);
        return -1;
    }
    close(fd);

    json_error_t err;
    json_t *resp = json_loads(resp_buf, 0, &err);
    if (!resp) {
        log_error("IPC response parse error: %s", err.text);
        return -1;
    }

    const char *status = json_string_value(json_object_get(resp, "status"));
    if (!status || strcmp(status, "ok") != 0) {
        char *dump = json_dumps(resp, JSON_COMPACT);
        log_error("IPC request failed (%s): %s", action, dump ? dump : "unknown");
        free(dump);
        json_decref(resp);
        return -1;
    }

    if (out_resp) {
        *out_resp = resp;
    } else {
        json_decref(resp);
    }
    return 0;
}

int ipc_client_register(void) {
    json_t *data = json_object();
    json_object_set_new(data, "service_name", json_string(service_name));
    json_object_set_new(data, "metadata", json_pack("{s:s}", "type", "brain_google_api"));

    int rc = daemon_request("service_register", data, NULL);
    json_decref(data);
    if (rc == 0) {
        log_info("IPC registered via service_register: %s", service_name);
    }
    return rc;
}

int ipc_client_send(const char *to, const char *message_type, const char *message) {
    json_t *data = json_object();
    json_object_set_new(data, "from", json_string(service_name));
    json_object_set_new(data, "to", json_string(to));
    json_object_set_new(data, "message_type", json_string(message_type ? message_type : "request"));

    json_t *payload = json_object();
    json_object_set_new(payload, "content", json_string(message ? message : ""));
    json_object_set_new(data, "payload", payload);

    int rc = daemon_request("ipc_send", data, NULL);
    json_decref(data);
    return rc;
}

int ipc_client_receive(char **out_type, char **out_payload) {
    if (!out_type || !out_payload) return -1;
    *out_type = NULL;
    *out_payload = NULL;

    json_t *data = json_object();
    json_object_set_new(data, "agent", json_string(service_name));
    json_object_set_new(data, "ack_mode", json_string("auto"));
    json_object_set_new(data, "max_items", json_integer(1));

    json_t *resp = NULL;
    int rc = daemon_request("ipc_recv", data, &resp);
    json_decref(data);
    if (rc != 0 || !resp) return -1;

    json_t *messages = json_object_get(resp, "messages");
    if (!messages || !json_is_array(messages) || json_array_size(messages) == 0) {
        json_decref(resp);
        return -1;
    }

    json_t *msg = json_array_get(messages, 0);
    const char *msg_type = json_string_value(json_object_get(msg, "message_type"));
    if (!msg_type) msg_type = "request";

    json_t *payload = json_object_get(msg, "payload");
    char *payload_str = payload ? json_dumps(payload, JSON_COMPACT) : strdup("{}");
    if (!payload_str) {
        json_decref(resp);
        return -1;
    }

    *out_type = strdup(msg_type);
    *out_payload = payload_str;
    json_decref(resp);
    return (*out_type && *out_payload) ? 0 : -1;
}

int ipc_client_notify(const char *message) {
    log_info("IPC notify: %s", message);
    return ipc_client_send("*", "notification", message);
}

void ipc_client_free(void) {
    log_info("IPC client freed");
}
