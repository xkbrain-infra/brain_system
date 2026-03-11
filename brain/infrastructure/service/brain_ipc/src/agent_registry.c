#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <pthread.h>
#include "agent_registry.h"

// ============ Initialization ============

void registry_init(AgentRegistry *reg) {
    memset(reg, 0, sizeof(AgentRegistry));
    pthread_mutex_init(&reg->lock, NULL);
}

void registry_destroy(AgentRegistry *reg) {
    pthread_mutex_destroy(&reg->lock);
}

// ============ Instance ID Utilities ============

void build_instance_id(char *buf, size_t size, const char *name,
                       const char *tmux_session, const char *tmux_pane) {
    if (!name || !name[0]) {
        buf[0] = '\0';
        return;
    }

    // Format: name@session:pane or name@session or name
    if (tmux_pane && tmux_pane[0]) {
        const char *session = (tmux_session && tmux_session[0]) ? tmux_session : "unknown";
        snprintf(buf, size, "%s@%s:%s", name, session, tmux_pane);
    } else if (tmux_session && tmux_session[0]) {
        snprintf(buf, size, "%s@%s", name, tmux_session);
    } else {
        snprintf(buf, size, "%s", name);
    }
}

int parse_instance_id(const char *instance_id, char *name, size_t name_size,
                      char *session, size_t session_size,
                      char *pane, size_t pane_size) {
    if (!instance_id || !instance_id[0]) {
        if (name) name[0] = '\0';
        if (session) session[0] = '\0';
        if (pane) pane[0] = '\0';
        return -1;
    }

    // Find @ separator
    const char *at = strchr(instance_id, '@');
    if (!at) {
        // Just name
        if (name) strncpy(name, instance_id, name_size - 1);
        if (session) session[0] = '\0';
        if (pane) pane[0] = '\0';
        return 0;
    }

    // Extract name
    if (name) {
        size_t name_len = at - instance_id;
        if (name_len >= name_size) name_len = name_size - 1;
        strncpy(name, instance_id, name_len);
        name[name_len] = '\0';
    }

    // Find : separator for pane
    const char *colon = strchr(at + 1, ':');
    if (!colon) {
        // Just name@session
        if (session) strncpy(session, at + 1, session_size - 1);
        if (pane) pane[0] = '\0';
        return 0;
    }

    // Extract session and pane
    if (session) {
        size_t session_len = colon - (at + 1);
        if (session_len >= session_size) session_len = session_size - 1;
        strncpy(session, at + 1, session_len);
        session[session_len] = '\0';
    }
    if (pane) {
        strncpy(pane, colon + 1, pane_size - 1);
    }

    return 0;
}

// ============ Internal Helpers ============

static Agent* find_agent_by_name(AgentRegistry *reg, const char *name) {
    for (int i = 0; i < reg->count; i++) {
        if (reg->agents[i].active && strcmp(reg->agents[i].name, name) == 0) {
            return &reg->agents[i];
        }
    }
    return NULL;
}

static Agent* find_agent_by_instance_id(AgentRegistry *reg, const char *instance_id) {
    for (int i = 0; i < reg->count; i++) {
        if (reg->agents[i].active && strcmp(reg->agents[i].instance_id, instance_id) == 0) {
            return &reg->agents[i];
        }
    }
    return NULL;
}

static Agent* find_agent_by_pane(AgentRegistry *reg, const char *tmux_pane) {
    for (int i = 0; i < reg->count; i++) {
        if (reg->agents[i].active && strcmp(reg->agents[i].tmux_pane, tmux_pane) == 0) {
            return &reg->agents[i];
        }
    }
    return NULL;
}

static bool is_agent_online(Agent *agent, time_t now) {
    if (!agent || !agent->active) return false;
    return (now - agent->last_heartbeat) < HEARTBEAT_TIMEOUT;
}

static const char *source_to_str(AgentSource source) {
    switch (source) {
        case AGENT_SOURCE_REGISTER: return "register";
        case AGENT_SOURCE_HEARTBEAT: return "heartbeat";
        case AGENT_SOURCE_TMUX_DISCOVERY: return "tmux_discovery";
        case AGENT_SOURCE_SERVICE: return "service";
        default: return "unknown";
    }
}

static bool matches_source_filter(const Agent *a, int source_filter) {
    if (!a) return false;
    if (source_filter == REGISTRY_SOURCE_FILTER_ALL) return true;
    if (source_filter == REGISTRY_SOURCE_FILTER_AGENT) {
        // Exclude both AGENT_SOURCE_SERVICE and names starting with service-
        if (a->source == AGENT_SOURCE_SERVICE) return false;
        if (strncmp(a->name, "service-", 8) == 0) return false;
        return true;
    }
    if (source_filter == REGISTRY_SOURCE_FILTER_SERVICE) {
        // Include either AGENT_SOURCE_SERVICE or names starting with service-
        if (a->source == AGENT_SOURCE_SERVICE) return true;
        if (strncmp(a->name, "service-", 8) == 0) return true;
        return false;
    }
    return (int)a->source == source_filter;
}

static bool matches_query(const Agent *a, const char *query, bool fuzzy) {
    if (!a) return false;
    if (!query || !query[0]) return true;

    const char *source = source_to_str(a->source);
    if (fuzzy) {
        return (strcasestr(a->name, query) != NULL) ||
               (strcasestr(a->instance_id, query) != NULL) ||
               (strcasestr(a->tmux_session, query) != NULL) ||
               (strcasestr(a->tmux_pane, query) != NULL) ||
               (strcasestr(a->pty_path, query) != NULL) ||
               (strcasestr(source, query) != NULL);
    }

    return (strcasecmp(a->name, query) == 0) ||
           (strcasecmp(a->instance_id, query) == 0) ||
           (strcasecmp(a->tmux_session, query) == 0) ||
           (strcasecmp(a->tmux_pane, query) == 0) ||
           (strcasecmp(a->pty_path, query) == 0) ||
           (strcasecmp(source, query) == 0);
}

static int find_empty_slot(AgentRegistry *reg) {
    for (int i = 0; i < reg->count; i++) {
        if (!reg->agents[i].active) {
            return i;
        }
    }
    if (reg->count >= MAX_AGENTS) {
        return -1;
    }
    return reg->count++;
}

static bool pane_in_snapshot(const char *pane, const char **pane_ids, int pane_count) {
    if (!pane || !pane[0]) return true; // No pane info: don't prune here
    for (int i = 0; i < pane_count; i++) {
        const char *p = pane_ids[i];
        if (!p || !p[0]) continue;
        if (strcmp(p, pane) == 0) return true;
    }
    return false;
}

// ============ Registration ============

int registry_register(AgentRegistry *reg, const char *name, const char *tmux_pane) {
    return registry_register_full(reg, name, NULL, tmux_pane, NULL, AGENT_SOURCE_REGISTER);
}

int registry_register_full(AgentRegistry *reg, const char *name,
                           const char *tmux_session, const char *tmux_pane,
                           const char *metadata, AgentSource source) {
    if (!name || !name[0]) return -1;

    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);

    // Build instance_id
    char instance_id[MAX_INSTANCE_ID];
    build_instance_id(instance_id, sizeof(instance_id), name, tmux_session, tmux_pane);

    // One tmux pane should map to exactly one active agent instance.
    // If multiple identities register to the same pane (misconfiguration),
    // keep the most recent registration and mark others inactive.
    if (tmux_pane && tmux_pane[0]) {
        for (int i = 0; i < reg->count; i++) {
            Agent *a = &reg->agents[i];
            if (!a->active) continue;
            if (!a->tmux_pane[0]) continue;
            if (strcmp(a->tmux_pane, tmux_pane) != 0) continue;
            if (strcmp(a->instance_id, instance_id) == 0) continue;
            a->active = false;
        }
    }

    // Check if instance already exists
    Agent *existing = find_agent_by_instance_id(reg, instance_id);
    if (existing) {
        existing->last_heartbeat = now;
        if (tmux_pane && tmux_pane[0]) {
            strncpy(existing->tmux_pane, tmux_pane, MAX_TMUX_PANE - 1);
        }
        if (tmux_session && tmux_session[0]) {
            strncpy(existing->tmux_session, tmux_session, MAX_TMUX_SESSION - 1);
        }
        if (metadata && metadata[0]) {
            strncpy(existing->metadata, metadata, MAX_METADATA_SIZE - 1);
        }
        if (source == AGENT_SOURCE_TMUX_DISCOVERY) {
            existing->discovered_at = now;
        }
        pthread_mutex_unlock(&reg->lock);
        return 0;
    }

    // Find empty slot
    int slot = find_empty_slot(reg);
    if (slot < 0) {
        pthread_mutex_unlock(&reg->lock);
        return -1;  // Full
    }

    Agent *agent = &reg->agents[slot];
    memset(agent, 0, sizeof(Agent));

    strncpy(agent->name, name, MAX_AGENT_NAME - 1);
    strncpy(agent->instance_id, instance_id, MAX_INSTANCE_ID - 1);

    if (tmux_pane && tmux_pane[0]) {
        strncpy(agent->tmux_pane, tmux_pane, MAX_TMUX_PANE - 1);
    }
    if (tmux_session && tmux_session[0]) {
        strncpy(agent->tmux_session, tmux_session, MAX_TMUX_SESSION - 1);
    }
    if (metadata && metadata[0]) {
        strncpy(agent->metadata, metadata, MAX_METADATA_SIZE - 1);
    }

    agent->registered_at = now;
    agent->last_heartbeat = now;
    agent->source = source;
    agent->active = true;

    if (source == AGENT_SOURCE_TMUX_DISCOVERY) {
        agent->discovered_at = now;
    }

    pthread_mutex_unlock(&reg->lock);
    return 0;
}

int registry_heartbeat(AgentRegistry *reg, const char *name) {
    return registry_heartbeat_full(reg, name, NULL, NULL);
}

int registry_heartbeat_full(AgentRegistry *reg, const char *name,
                            const char *tmux_session, const char *tmux_pane) {
    if (!name || !name[0]) return -1;

    pthread_mutex_lock(&reg->lock);

    // Build instance_id and find
    char instance_id[MAX_INSTANCE_ID];
    build_instance_id(instance_id, sizeof(instance_id), name, tmux_session, tmux_pane);

    Agent *agent = find_agent_by_instance_id(reg, instance_id);
    if (!agent) {
        pthread_mutex_unlock(&reg->lock);
        // Auto-register on heartbeat
        // Fix: Use AGENT_SOURCE_SERVICE for service-* names
        AgentSource source = AGENT_SOURCE_HEARTBEAT;
        if (strncmp(name, "service-", 8) == 0) {
            source = AGENT_SOURCE_SERVICE;
        }
        return registry_register_full(reg, name, tmux_session, tmux_pane, NULL, source);
    }

    agent->last_heartbeat = time(NULL);
    pthread_mutex_unlock(&reg->lock);
    return 0;
}

int registry_unregister(AgentRegistry *reg, const char *name) {
    if (!name || !name[0]) return -1;

    pthread_mutex_lock(&reg->lock);

    int removed = 0;
    for (int i = 0; i < reg->count; i++) {
        if (reg->agents[i].active && strcmp(reg->agents[i].name, name) == 0) {
            reg->agents[i].active = false;
            removed++;
        }
    }

    pthread_mutex_unlock(&reg->lock);
    return removed > 0 ? 0 : -1;
}

int registry_unregister_instance(AgentRegistry *reg, const char *instance_id) {
    if (!instance_id || !instance_id[0]) return -1;

    pthread_mutex_lock(&reg->lock);

    Agent *agent = find_agent_by_instance_id(reg, instance_id);
    if (agent) {
        agent->active = false;
        pthread_mutex_unlock(&reg->lock);
        return 0;
    }

    pthread_mutex_unlock(&reg->lock);
    return -1;
}

// ============ Health / Pruning ============

int registry_prune_missing_panes(AgentRegistry *reg, const char **pane_ids, int pane_count) {
    if (!reg) return 0;

    pthread_mutex_lock(&reg->lock);

    int removed = 0;
    for (int i = 0; i < reg->count; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (a->source == AGENT_SOURCE_SERVICE) continue; // services have no tmux pane
        if (!a->tmux_pane[0]) continue;
        if (!pane_in_snapshot(a->tmux_pane, pane_ids, pane_count)) {
            a->active = false;
            removed++;
        }
    }

    pthread_mutex_unlock(&reg->lock);
    return removed;
}

// ============ Query ============

bool registry_is_online(AgentRegistry *reg, const char *name) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);

    // Check if any instance with this name is online
    for (int i = 0; i < reg->count; i++) {
        Agent *a = &reg->agents[i];
        if (a->active && strcmp(a->name, name) == 0) {
            if (is_agent_online(a, now)) {
                pthread_mutex_unlock(&reg->lock);
                return true;
            }
        }
    }

    pthread_mutex_unlock(&reg->lock);
    return false;
}

Agent* registry_get(AgentRegistry *reg, const char *name) {
    pthread_mutex_lock(&reg->lock);
    Agent *agent = find_agent_by_name(reg, name);
    pthread_mutex_unlock(&reg->lock);
    return agent;
}

Agent* registry_get_by_instance(AgentRegistry *reg, const char *instance_id) {
    pthread_mutex_lock(&reg->lock);
    Agent *agent = find_agent_by_instance_id(reg, instance_id);
    pthread_mutex_unlock(&reg->lock);
    return agent;
}

Agent* registry_get_by_tmux_pane(AgentRegistry *reg, const char *tmux_pane) {
    pthread_mutex_lock(&reg->lock);
    Agent *agent = find_agent_by_pane(reg, tmux_pane);
    pthread_mutex_unlock(&reg->lock);
    return agent;
}

int registry_list_online(AgentRegistry *reg, char *buf, size_t bufsize) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int count = 0;
    size_t offset = 0;

    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < reg->count && offset < bufsize - 200; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;

        bool online = is_agent_online(a, now);
        long idle = now - a->last_heartbeat;

        if (count > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }
        offset += snprintf(buf + offset, bufsize - offset,
            "{\"name\":\"%s\",\"instance_id\":\"%s\",\"online\":%s,"
            "\"registered_at\":%ld,\"last_heartbeat\":%ld,\"idle_seconds\":%ld,"
            "\"tmux_session\":\"%s\",\"tmux_pane\":\"%s\"}",
            a->name, a->instance_id, online ? "true" : "false",
            (long)a->registered_at, (long)a->last_heartbeat, idle,
            a->tmux_session, a->tmux_pane);
        count++;
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&reg->lock);
    return count;
}

int registry_list_instances(AgentRegistry *reg, char *buf, size_t bufsize,
                            bool include_offline, int source_filter) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int count = 0;
    size_t offset = 0;

    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < reg->count && offset < bufsize - 300; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (!matches_source_filter(a, source_filter)) continue;

        bool online = is_agent_online(a, now);
        if (!online && !include_offline) continue;

        long idle = now - a->last_heartbeat;
        const char *source_str = source_to_str(a->source);

        if (count > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }
        offset += snprintf(buf + offset, bufsize - offset,
            "{\"instance_id\":\"%s\",\"agent_name\":\"%s\",\"online\":%s,"
            "\"registered_at\":%ld,\"last_heartbeat\":%ld,\"idle_seconds\":%ld,"
            "\"tmux_session\":\"%s\",\"tmux_pane\":\"%s\",\"pty_path\":\"%s\",\"source\":\"%s\"}",
            a->instance_id, a->name, online ? "true" : "false",
            (long)a->registered_at, (long)a->last_heartbeat, idle,
            a->tmux_session, a->tmux_pane, a->pty_path, source_str);
        count++;
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&reg->lock);
    return count;
}

int registry_list_filtered(AgentRegistry *reg, char *buf, size_t bufsize,
                           bool include_offline, int source_filter) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int count = 0;
    size_t offset = 0;

    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < reg->count && offset < bufsize - 300; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (!matches_source_filter(a, source_filter)) continue;

        bool online = is_agent_online(a, now);
        if (!online && !include_offline) continue;

        long idle = now - a->last_heartbeat;
        const char *source_str = source_to_str(a->source);

        if (count > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }
        offset += snprintf(buf + offset, bufsize - offset,
            "{\"instance_id\":\"%s\",\"agent_name\":\"%s\",\"online\":%s,"
            "\"registered_at\":%ld,\"last_heartbeat\":%ld,\"idle_seconds\":%ld,"
            "\"tmux_session\":\"%s\",\"tmux_pane\":\"%s\",\"pty_path\":\"%s\",\"source\":\"%s\"}",
            a->instance_id, a->name, online ? "true" : "false",
            (long)a->registered_at, (long)a->last_heartbeat, idle,
            a->tmux_session, a->tmux_pane, a->pty_path, source_str);
        count++;
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&reg->lock);
    return count;
}

int registry_search(AgentRegistry *reg, const char *query, bool fuzzy,
                    bool include_offline, int source_filter, int limit,
                    char *buf, size_t bufsize) {
    if (limit <= 0) limit = 50;

    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int count = 0;
    size_t offset = 0;

    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < reg->count && offset < bufsize - 300; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (!matches_source_filter(a, source_filter)) continue;

        bool online = is_agent_online(a, now);
        if (!online && !include_offline) continue;
        if (!matches_query(a, query, fuzzy)) continue;

        long idle = now - a->last_heartbeat;
        const char *source_str = source_to_str(a->source);

        if (count > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }
        offset += snprintf(buf + offset, bufsize - offset,
            "{\"instance_id\":\"%s\",\"agent_name\":\"%s\",\"online\":%s,"
            "\"registered_at\":%ld,\"last_heartbeat\":%ld,\"idle_seconds\":%ld,"
            "\"tmux_session\":\"%s\",\"tmux_pane\":\"%s\",\"pty_path\":\"%s\",\"source\":\"%s\"}",
            a->instance_id, a->name, online ? "true" : "false",
            (long)a->registered_at, (long)a->last_heartbeat, idle,
            a->tmux_session, a->tmux_pane, a->pty_path, source_str);
        count++;
        if (count >= limit) break;
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&reg->lock);
    return count;
}

int registry_list_agents_aggregated(AgentRegistry *reg, char *buf, size_t bufsize,
                                    bool include_offline, int source_filter) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    size_t offset = 0;

    // 临时存储聚合结果: name -> 统计信息
    typedef struct {
        char name[MAX_AGENT_NAME];
        bool online;
        int instance_count;
        int online_instance_count;
        time_t first_registered_at;
        time_t last_heartbeat;
    } AgentAggregate;

    AgentAggregate aggregates[MAX_AGENTS] = {0};
    int aggregate_count = 0;

    // 第一步: 遍历所有实例，聚合统计
    for (int i = 0; i < reg->count; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (!matches_source_filter(a, source_filter)) continue;

        bool online = is_agent_online(a, now);
        if (!online && !include_offline) continue;

        // 查找是否已有该名称的聚合条目
        int found = -1;
        for (int j = 0; j < aggregate_count; j++) {
            if (strcmp(aggregates[j].name, a->name) == 0) {
                found = j;
                break;
            }
        }

        if (found >= 0) {
            // 更新现有聚合条目
            AgentAggregate *agg = &aggregates[found];
            agg->instance_count++;
            if (online) {
                agg->online = true;
                agg->online_instance_count++;
            }
            if (a->registered_at < agg->first_registered_at) {
                agg->first_registered_at = a->registered_at;
            }
            if (a->last_heartbeat > agg->last_heartbeat) {
                agg->last_heartbeat = a->last_heartbeat;
            }
        } else {
            // 创建新的聚合条目
            if (aggregate_count >= MAX_AGENTS) break;
            AgentAggregate *agg = &aggregates[aggregate_count++];
            strncpy(agg->name, a->name, MAX_AGENT_NAME - 1);
            agg->online = online;
            agg->instance_count = 1;
            agg->online_instance_count = online ? 1 : 0;
            agg->first_registered_at = a->registered_at;
            agg->last_heartbeat = a->last_heartbeat;
        }
    }

    // 第二步: 生成JSON
    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < aggregate_count && offset < bufsize - 200; i++) {
        AgentAggregate *agg = &aggregates[i];
        long idle = now - agg->last_heartbeat;

        if (i > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }
        offset += snprintf(buf + offset, bufsize - offset,
            "{\"name\":\"%s\",\"online\":%s,"
            "\"instance_count\":%d,\"online_instance_count\":%d,"
            "\"first_registered_at\":%ld,\"last_heartbeat\":%ld,"
            "\"idle_seconds\":%ld}",
            agg->name, agg->online ? "true" : "false",
            agg->instance_count, agg->online_instance_count,
            (long)agg->first_registered_at, (long)agg->last_heartbeat,
            idle);
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&reg->lock);
    return aggregate_count;
}

// ============ Target Resolution ============

// Helper: Choose best agent when multiple instances have same tmux_pane
// Prefers agent with complete tmux_session info
static Agent* pick_best_agent(Agent *agents[], int count) {
    if (count == 0) return NULL;
    if (count == 1) return agents[0];

    // Prefer agent with tmux_session set (more complete info)
    Agent *best = agents[0];
    for (int i = 1; i < count; i++) {
        if (agents[i]->tmux_session[0] && !best->tmux_session[0]) {
            best = agents[i];
        }
    }
    return best;
}

// Helper: Check if multiple agents are effectively the same (same pane)
static bool are_same_pane(Agent *agents[], int count) {
    if (count <= 1) return true;
    const char *pane = agents[0]->tmux_pane;
    if (!pane[0]) return false;  // No pane info, can't determine
    for (int i = 1; i < count; i++) {
        if (strcmp(agents[i]->tmux_pane, pane) != 0) {
            return false;
        }
    }
    return true;
}

int resolve_target(AgentRegistry *reg, const char *to,
                   char *resolved, size_t resolved_size,
                   Agent **out_agent, char *error_buf, size_t error_size) {
    if (!to || !to[0]) {
        if (error_buf) snprintf(error_buf, error_size, "missing 'to' field");
        return -1;
    }

    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);

    // Case 1: tmux:%pane_id routing
    if (strncmp(to, "tmux:", 5) == 0) {
        const char *pane = to + 5;
        if (!pane[0]) {
            if (error_buf) snprintf(error_buf, error_size, "invalid target: tmux:<pane_id> required");
            pthread_mutex_unlock(&reg->lock);
            return -1;
        }

        // Find all agents by pane
        Agent *matches[MAX_AGENTS];
        int match_count = 0;
        for (int i = 0; i < reg->count && match_count < MAX_AGENTS; i++) {
            Agent *a = &reg->agents[i];
            if (!a->active) continue;
            if (strcmp(a->tmux_pane, pane) == 0 && is_agent_online(a, now)) {
                matches[match_count++] = a;
            }
        }

        if (match_count == 0) {
            // Try stale agents as fallback
            for (int i = 0; i < reg->count && match_count < MAX_AGENTS; i++) {
                Agent *a = &reg->agents[i];
                if (a->active && strcmp(a->tmux_pane, pane) == 0) {
                    matches[match_count++] = a;
                }
            }
        }

        if (match_count > 0) {
            Agent *best = pick_best_agent(matches, match_count);
            strncpy(resolved, best->instance_id, resolved_size - 1);
            if (out_agent) *out_agent = best;
            pthread_mutex_unlock(&reg->lock);
            return 0;
        }

        if (error_buf) snprintf(error_buf, error_size, "no agent instance found for %s", to);
        pthread_mutex_unlock(&reg->lock);
        return -1;
    }

    // Case 2: Instance ID routing (contains @)
    if (strchr(to, '@')) {
        // Parse the instance_id to extract name and pane
        char parsed_name[MAX_AGENT_NAME], parsed_session[MAX_TMUX_SESSION], parsed_pane[MAX_TMUX_PANE];
        parse_instance_id(to, parsed_name, sizeof(parsed_name),
                         parsed_session, sizeof(parsed_session), parsed_pane, sizeof(parsed_pane));

        // If we have a pane, look for a better match (one with complete tmux_session)
        if (parsed_pane[0]) {
            Agent *matches[MAX_AGENTS];
            int match_count = 0;
            for (int i = 0; i < reg->count && match_count < MAX_AGENTS; i++) {
                Agent *a = &reg->agents[i];
                if (!a->active) continue;
                if (strcmp(a->name, parsed_name) == 0 &&
                    strcmp(a->tmux_pane, parsed_pane) == 0 &&
                    is_agent_online(a, now)) {
                    matches[match_count++] = a;
                }
            }
            if (match_count > 0) {
                Agent *best = pick_best_agent(matches, match_count);
                strncpy(resolved, best->instance_id, resolved_size - 1);
                if (out_agent) *out_agent = best;
                pthread_mutex_unlock(&reg->lock);
                return 0;
            }
        }

        // Fallback: if no pane, try logical name resolution (like Case 3)
        if (!parsed_pane[0]) {
            for (int i = 0; i < reg->count && i < MAX_AGENTS; i++) {
                Agent *a = &reg->agents[i];
                if (!a->active) continue;
                if (strcmp(a->name, parsed_name) == 0 && is_agent_online(a, now)) {
                    strncpy(resolved, a->instance_id, resolved_size - 1);
                    if (out_agent) *out_agent = a;
                    pthread_mutex_unlock(&reg->lock);
                    return 0;
                }
            }
        }
        // Final fallback: use original instance_id
        Agent *agent = find_agent_by_instance_id(reg, to);
        strncpy(resolved, to, resolved_size - 1);
        if (out_agent) *out_agent = agent;
        pthread_mutex_unlock(&reg->lock);
        return 0;
    }

    // Case 3: Plain logical name routing
    Agent *matches[MAX_AGENTS];
    int online_count = 0;
    for (int i = 0; i < reg->count && online_count < MAX_AGENTS; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        if (strcmp(a->name, to) == 0 && is_agent_online(a, now)) {
            matches[online_count++] = a;
        }
    }

    if (online_count > 1) {
        // Check if they're actually the same pane (MCP + tmux_discovery race)
        if (are_same_pane(matches, online_count)) {
            Agent *best = pick_best_agent(matches, online_count);
            strncpy(resolved, best->instance_id, resolved_size - 1);
            if (out_agent) *out_agent = best;
            pthread_mutex_unlock(&reg->lock);
            return 0;
        }
        // Not same pane - prefer the instance with a tmux_pane (from tmux_discovery)
        // over a bare heartbeat-registered instance without pane
        Agent *with_pane = NULL;
        int pane_count = 0;
        for (int i = 0; i < online_count; i++) {
            if (matches[i]->tmux_pane[0]) {
                with_pane = matches[i];
                pane_count++;
            }
        }
        if (pane_count == 1) {
            // Exactly one has a pane - use it (the other is a stale heartbeat entry)
            strncpy(resolved, with_pane->instance_id, resolved_size - 1);
            if (out_agent) *out_agent = with_pane;
            pthread_mutex_unlock(&reg->lock);
            return 0;
        }
        // Truly ambiguous - multiple different panes
        if (error_buf) snprintf(error_buf, error_size,
            "ambiguous target agent_name='%s' (multiple online instances)", to);
        pthread_mutex_unlock(&reg->lock);
        return -1;
    }

    if (online_count == 1) {
        strncpy(resolved, matches[0]->instance_id, resolved_size - 1);
        if (out_agent) *out_agent = matches[0];
        pthread_mutex_unlock(&reg->lock);
        return 0;
    }

    // No online instance, use logical name for offline queueing
    strncpy(resolved, to, resolved_size - 1);
    if (out_agent) *out_agent = NULL;
    pthread_mutex_unlock(&reg->lock);
    return 0;
}

// ============ Tmux Discovery ============

int registry_update_from_tmux(AgentRegistry *reg, const char *pane_id,
                              const char *session_name, const char *agent_name) {
    return registry_register_full(reg, agent_name, session_name, pane_id,
                                  NULL, AGENT_SOURCE_TMUX_DISCOVERY);
}

// ============ Statistics ============

void registry_stats(AgentRegistry *reg, char *buf, size_t bufsize) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int total = 0;
    int online = 0;
    int from_register = 0;
    int from_heartbeat = 0;
    int from_discovery = 0;
    int from_service = 0;

    for (int i = 0; i < reg->count; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        total++;
        if (is_agent_online(a, now)) online++;
        switch (a->source) {
            case AGENT_SOURCE_REGISTER: from_register++; break;
            case AGENT_SOURCE_HEARTBEAT: from_heartbeat++; break;
            case AGENT_SOURCE_TMUX_DISCOVERY: from_discovery++; break;
            case AGENT_SOURCE_SERVICE: from_service++; break;
        }
    }

    snprintf(buf, bufsize,
        "{\"total_instances\":%d,\"online\":%d,\"offline\":%d,"
        "\"from_register\":%d,\"from_heartbeat\":%d,\"from_discovery\":%d,\"from_service\":%d}",
        total, online, total - online,
        from_register, from_heartbeat, from_discovery, from_service);

    pthread_mutex_unlock(&reg->lock);
}

// ============ Stale Entry Eviction ============

int registry_evict_stale(AgentRegistry *reg) {
    pthread_mutex_lock(&reg->lock);

    time_t now = time(NULL);
    int evicted = 0;

    for (int i = 0; i < reg->count; i++) {
        Agent *a = &reg->agents[i];
        if (!a->active) continue;
        // tmux_discovery entries are managed by registry_prune_missing_panes
        if (a->source == AGENT_SOURCE_TMUX_DISCOVERY) continue;
        if ((now - a->last_heartbeat) > EVICT_TIMEOUT) {
            a->active = false;
            evicted++;
        }
    }

    pthread_mutex_unlock(&reg->lock);
    return evicted;
}
