#ifndef AGENT_REGISTRY_H
#define AGENT_REGISTRY_H

#include <time.h>
#include <stdbool.h>
#include <pthread.h>

#define MAX_AGENTS 256
#define MAX_AGENT_NAME 64
#define MAX_INSTANCE_ID 128
#define MAX_TMUX_SESSION 64
#define MAX_TMUX_PANE 32
#define MAX_PTY_PATH 256
#define MAX_METADATA_SIZE 1024
#define HEARTBEAT_TIMEOUT 300   // 5 minutes: mark offline
#define EVICT_TIMEOUT     3600  // 1 hour: remove from registry

// Agent source types
typedef enum {
    AGENT_SOURCE_REGISTER,      // Manual registration via agent_register
    AGENT_SOURCE_HEARTBEAT,     // Auto-registered via heartbeat
    AGENT_SOURCE_TMUX_DISCOVERY,// Discovered via tmux list-panes
    AGENT_SOURCE_SERVICE        // Service registration (no tmux, long-lived)
} AgentSource;

typedef struct {
    char name[MAX_AGENT_NAME];           // Logical name (claude/codex)
    char instance_id[MAX_INSTANCE_ID];   // Full ID: name@session:pane
    char tmux_session[MAX_TMUX_SESSION]; // tmux session name
    char tmux_pane[MAX_TMUX_PANE];       // tmux pane ID (%0, %1, etc)
    char pty_path[MAX_PTY_PATH];         // PTY device path for non-tmux notification
    char metadata[MAX_METADATA_SIZE];    // JSON metadata (optional)
    time_t registered_at;
    time_t last_heartbeat;
    time_t discovered_at;                // Last tmux discovery time
    AgentSource source;
    bool active;
} Agent;

typedef struct {
    Agent agents[MAX_AGENTS];
    int count;
    pthread_mutex_t lock;
} AgentRegistry;

#define REGISTRY_SOURCE_FILTER_ALL      (-1)
#define REGISTRY_SOURCE_FILTER_AGENT    (-2)
#define REGISTRY_SOURCE_FILTER_SERVICE  (-3)

// Initialization
void registry_init(AgentRegistry *reg);
void registry_destroy(AgentRegistry *reg);

// Registration
int registry_register(AgentRegistry *reg, const char *name, const char *tmux_pane);
int registry_register_full(AgentRegistry *reg, const char *name,
                           const char *tmux_session, const char *tmux_pane,
                           const char *metadata, AgentSource source);
int registry_heartbeat(AgentRegistry *reg, const char *name);
int registry_heartbeat_full(AgentRegistry *reg, const char *name,
                            const char *tmux_session, const char *tmux_pane);
int registry_unregister(AgentRegistry *reg, const char *name);
int registry_unregister_instance(AgentRegistry *reg, const char *instance_id);

// Query
bool registry_is_online(AgentRegistry *reg, const char *name);
Agent* registry_get(AgentRegistry *reg, const char *name);
Agent* registry_get_by_instance(AgentRegistry *reg, const char *instance_id);
Agent* registry_get_by_tmux_pane(AgentRegistry *reg, const char *tmux_pane);
int registry_list_online(AgentRegistry *reg, char *buf, size_t bufsize);
int registry_list_instances(AgentRegistry *reg, char *buf, size_t bufsize, bool include_offline);
int registry_list_filtered(AgentRegistry *reg, char *buf, size_t bufsize,
                           bool include_offline, int source_filter);
int registry_search(AgentRegistry *reg, const char *query, bool fuzzy,
                    bool include_offline, int source_filter, int limit,
                    char *buf, size_t bufsize);

// Health/pruning
// Marks active agents as inactive when their tmux_pane is not present in the provided snapshot.
// Returns number of agents marked inactive.
int registry_prune_missing_panes(AgentRegistry *reg, const char **pane_ids, int pane_count);

// Evicts non-tmux agents that have been offline longer than EVICT_TIMEOUT.
// Returns number of evicted entries.
int registry_evict_stale(AgentRegistry *reg);

// Instance ID utilities
void build_instance_id(char *buf, size_t size, const char *name,
                       const char *tmux_session, const char *tmux_pane);
int parse_instance_id(const char *instance_id, char *name, size_t name_size,
                      char *session, size_t session_size,
                      char *pane, size_t pane_size);

// Target resolution for IPC routing
// Supports: tmux:%pane, instance_id (name@session:pane), logical name
// Returns: resolved instance_id (or logical name for offline queueing)
int resolve_target(AgentRegistry *reg, const char *to,
                   char *resolved, size_t resolved_size,
                   Agent **out_agent, char *error_buf, size_t error_size);

// Tmux discovery
int registry_update_from_tmux(AgentRegistry *reg, const char *pane_id,
                              const char *session_name, const char *agent_name);

// Statistics
void registry_stats(AgentRegistry *reg, char *buf, size_t bufsize);

#endif
