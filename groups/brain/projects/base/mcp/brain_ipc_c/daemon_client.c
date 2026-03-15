#include "daemon_client.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static char *dup_err(const char *msg) {
  if (!msg) msg = "unknown error";
  size_t n = strlen(msg) + 1;
  char *out = (char *)malloc(n);
  if (!out) return NULL;
  memcpy(out, msg, n);
  return out;
}

void daemon_client_init(DaemonClient *c, const char *socket_path) {
  c->socket_path = socket_path;
}

json_t *daemon_request(DaemonClient *c, const char *action, json_t *data, char **err_out) {
  if (err_out) *err_out = NULL;
  if (!c || !c->socket_path || !action) {
    if (err_out) *err_out = dup_err("invalid client/action");
    return NULL;
  }

  json_t *req = json_object();
  json_object_set_new(req, "action", json_string(action));
  json_object_set(req, "data", data ? data : json_object());

  char *line = json_dumps(req, JSON_COMPACT);
  json_decref(req);
  if (!line) {
    if (err_out) *err_out = dup_err("json_dumps failed");
    return NULL;
  }

  size_t line_len = strlen(line);
  char *sendbuf = (char *)malloc(line_len + 2);
  if (!sendbuf) {
    free(line);
    if (err_out) *err_out = dup_err("oom");
    return NULL;
  }
  memcpy(sendbuf, line, line_len);
  sendbuf[line_len] = '\n';
  sendbuf[line_len + 1] = '\0';
  free(line);

  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    free(sendbuf);
    if (err_out) *err_out = dup_err(strerror(errno));
    return NULL;
  }

  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, c->socket_path, sizeof(addr.sun_path) - 1);
  if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    close(fd);
    free(sendbuf);
    if (err_out) *err_out = dup_err(strerror(errno));
    return NULL;
  }

  ssize_t off = 0;
  ssize_t total = (ssize_t)strlen(sendbuf);
  while (off < total) {
    ssize_t n = write(fd, sendbuf + off, (size_t)(total - off));
    if (n < 0) {
      if (errno == EINTR) continue;
      close(fd);
      free(sendbuf);
      if (err_out) *err_out = dup_err(strerror(errno));
      return NULL;
    }
    off += n;
  }
  free(sendbuf);

  /* read a single line response */
  size_t cap = 1 << 20;
  char *buf = (char *)malloc(cap);
  if (!buf) {
    close(fd);
    if (err_out) *err_out = dup_err("oom");
    return NULL;
  }
  size_t used = 0;
  while (used + 1 < cap) {
    char ch;
    ssize_t n = read(fd, &ch, 1);
    if (n == 0) break;
    if (n < 0) {
      if (errno == EINTR) continue;
      free(buf);
      close(fd);
      if (err_out) *err_out = dup_err(strerror(errno));
      return NULL;
    }
    buf[used++] = ch;
    if (ch == '\n') break;
  }
  buf[used] = '\0';
  close(fd);

  if (used == 0) {
    free(buf);
    if (err_out) *err_out = dup_err("empty response from daemon");
    return NULL;
  }

  json_error_t jerr;
  json_t *resp = json_loads(buf, 0, &jerr);
  free(buf);
  if (!resp) {
    if (err_out) *err_out = dup_err(jerr.text);
    return NULL;
  }
  return resp;
}

