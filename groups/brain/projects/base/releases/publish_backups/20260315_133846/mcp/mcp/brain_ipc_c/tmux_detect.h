#pragma once

/* Best-effort tmux detection used to build a stable agent_id. */

const char *tmux_get_pane_id(void);     /* pointer valid for process lifetime */
const char *tmux_get_session_name(void);/* pointer valid for process lifetime */

