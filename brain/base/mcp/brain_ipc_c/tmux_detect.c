#include "tmux_detect.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static char g_pane[64] = {0};
static char g_session[128] = {0};
static int g_resolved = 0;

static void trim(char *s) {
  if (!s) return;
  size_t n = strlen(s);
  while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t'))
    s[--n] = '\0';
}

static void run_tmux_cmd(const char *cmd, char *out, size_t out_sz) {
  if (!out || out_sz == 0) return;
  out[0] = '\0';
  FILE *fp = popen(cmd, "r");
  if (!fp) return;
  if (fgets(out, (int)out_sz, fp)) {
    trim(out);
  }
  pclose(fp);
}

/*
 * Resolve session name and pane ID by looking up our own tty
 * in tmux's pane list. This works even when TMUX/TMUX_PANE env
 * vars are not set (e.g. Codex CLI strips them from child processes).
 */
static void resolve_by_tty(void) {
  if (g_resolved) return;
  g_resolved = 1;

  /* Try env vars first (fast path for Claude Code) */
  const char *env_pane = getenv("TMUX_PANE");
  const char *env_sess = getenv("TMUX_SESSION");
  const char *brain_pane = getenv("BRAIN_TMUX_PANE");
  const char *brain_sess = getenv("BRAIN_TMUX_SESSION");
  if ((!env_pane || !env_pane[0]) && brain_pane && brain_pane[0]) {
    env_pane = brain_pane;
  }
  if ((!env_sess || !env_sess[0]) && brain_sess && brain_sess[0]) {
    env_sess = brain_sess;
  }
  if (env_pane && env_pane[0] && env_sess && env_sess[0]) {
    snprintf(g_pane, sizeof(g_pane), "%s", env_pane);
    snprintf(g_session, sizeof(g_session), "%s", env_sess);
    return;
  }

  /* Try TMUX env + display-message (works when TMUX is set) */
  if (getenv("TMUX") && getenv("TMUX")[0]) {
    if (!g_pane[0])
      run_tmux_cmd("tmux display-message -p '#{pane_id}' 2>/dev/null", g_pane, sizeof(g_pane));
    if (!g_session[0])
      run_tmux_cmd("tmux display-message -p '#S' 2>/dev/null", g_session, sizeof(g_session));
    if (g_pane[0] && g_session[0]) return;
  }

  /* Try BRAIN_TMUX_SESSION env (set by Codex config.toml for MCP servers).
     Codex strips TMUX/TMUX_PANE but passes BRAIN_* env vars. */
  if (brain_sess && brain_sess[0]) {
    snprintf(g_session, sizeof(g_session), "%s", brain_sess);
    /* Look up pane ID for this session via tmux */
    char cmd[256];
    snprintf(cmd, sizeof(cmd),
        "tmux list-panes -t '%s' -F '#{pane_id}' 2>/dev/null | head -1", brain_sess);
    run_tmux_cmd(cmd, g_pane, sizeof(g_pane));
    if (g_pane[0]) return;
  }
}

const char *tmux_get_pane_id(void) {
  resolve_by_tty();
  return g_pane;
}

const char *tmux_get_session_name(void) {
  resolve_by_tty();
  return g_session;
}
