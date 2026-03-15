#include "notify_bridge.h"
#include "tmux_detect.h"

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include <jansson.h>

static int connect_notify(const char *path) {
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);
  if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    close(fd);
    return -1;
  }
  return fd;
}

static void reregister_with_daemon(NotifyBridge *b) {
  if (!b->dc || !b->agent_name) return;
  json_t *data = json_object();
  json_object_set_new(data, "agent_name", json_string(b->agent_name));
  json_object_set_new(data, "metadata", json_pack("{s:b}", "reconnected", 1));
  const char *pane = tmux_get_pane_id();
  const char *session = tmux_get_session_name();
  if (pane && pane[0]) json_object_set_new(data, "tmux_pane", json_string(pane));
  if (session && session[0]) json_object_set_new(data, "tmux_session", json_string(session));
  char *err = NULL;
  json_t *resp = daemon_request(b->dc, "agent_register", data, &err);
  json_decref(data);
  if (resp) json_decref(resp);
  free(err);
}

static void *bridge_thread(void *arg) {
  NotifyBridge *b = (NotifyBridge *)arg;
  const char *path = b->notify_socket_path;
  int had_connection = 0;
  while (!*(b->shutdown_flag)) {
    int fd = connect_notify(path);
    if (fd < 0) {
      usleep(250 * 1000);
      continue;
    }

    if (had_connection) {
      /* reconnected after a disconnect → daemon likely restarted */
      reregister_with_daemon(b);
    }
    had_connection = 1;

    /* Drain the notify socket (wake-up only; we don't parse or relay events) */
    char buf[4096];
    while (!*(b->shutdown_flag)) {
      ssize_t n = read(fd, buf, sizeof(buf));
      if (n == 0) break;
      if (n < 0) {
        if (errno == EINTR) continue;
        break;
      }
    }
    close(fd);
  }
  return NULL;
}

int notify_bridge_start(NotifyBridge *b) {
  if (!b || !b->notify_socket_path || !b->shutdown_flag) return -1;
  NotifyBridge *s = (NotifyBridge *)malloc(sizeof(NotifyBridge));
  if (!s) return -1;
  *s = *b;
  pthread_t tid;
  int rc = pthread_create(&tid, NULL, bridge_thread, s);
  if (rc != 0) {
    free(s);
    return -1;
  }
  pthread_detach(tid);
  return 0;
}
