#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "conversation.h"

// Forward declaration from msgqueue.h
void generate_msg_id(char *buf, size_t size);

// ============ Initialization ============

void conversation_manager_init(ConversationManager *cm) {
    conversation_manager_init_with_config(cm, DEFAULT_STALE_HOURS);
}

void conversation_manager_init_with_config(ConversationManager *cm, int stale_hours) {
    memset(cm, 0, sizeof(ConversationManager));
    cm->stale_threshold_seconds = stale_hours * 3600;
    cm->running = true;
    pthread_mutex_init(&cm->lock, NULL);
}

void conversation_manager_destroy(ConversationManager *cm) {
    pthread_mutex_destroy(&cm->lock);
}

// ============ Internal Helpers ============

static Conversation* find_conversation(ConversationManager *cm, const char *conversation_id) {
    for (int i = 0; i < cm->count; i++) {
        if (cm->conversations[i].active &&
            strcmp(cm->conversations[i].conversation_id, conversation_id) == 0) {
            return &cm->conversations[i];
        }
    }
    return NULL;
}

static int find_empty_slot(ConversationManager *cm) {
    for (int i = 0; i < cm->count; i++) {
        if (!cm->conversations[i].active) {
            return i;
        }
    }
    if (cm->count >= MAX_CONVERSATIONS) {
        return -1;
    }
    return cm->count++;
}

static int parse_participants(const char *participants, Conversation *conv) {
    if (!participants || !participants[0]) return -1;

    conv->participant_count = 0;
    char buf[512];
    strncpy(buf, participants, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *saveptr;
    char *token = strtok_r(buf, ",", &saveptr);
    while (token && conv->participant_count < MAX_PARTICIPANTS) {
        // Trim whitespace
        while (*token == ' ') token++;
        char *end = token + strlen(token) - 1;
        while (end > token && *end == ' ') *end-- = '\0';

        if (*token) {
            strncpy(conv->participants[conv->participant_count], token, MAX_PARTICIPANT_NAME - 1);
            conv->participant_count++;
        }
        token = strtok_r(NULL, ",", &saveptr);
    }

    return conv->participant_count >= 2 ? 0 : -1;
}

static bool is_conversation_stale(Conversation *conv, time_t now, int threshold) {
    if (!conv->active) return true;
    return (now - conv->last_activity) > threshold;
}

// ============ Public API ============

char* conversation_create(ConversationManager *cm, const char *participants,
                          const char *metadata, char *conv_id_buf, size_t buf_size) {
    if (!participants || !participants[0]) {
        return NULL;
    }

    pthread_mutex_lock(&cm->lock);

    int slot = find_empty_slot(cm);
    if (slot < 0) {
        pthread_mutex_unlock(&cm->lock);
        return NULL; // Full
    }

    Conversation *conv = &cm->conversations[slot];
    memset(conv, 0, sizeof(Conversation));

    // Parse participants
    if (parse_participants(participants, conv) != 0) {
        pthread_mutex_unlock(&cm->lock);
        return NULL; // Invalid participants
    }

    // Generate conversation ID
    generate_msg_id(conv->conversation_id, sizeof(conv->conversation_id));

    // Set metadata
    if (metadata && metadata[0]) {
        strncpy(conv->metadata, metadata, MAX_CONV_METADATA_SIZE - 1);
    }

    time_t now = time(NULL);
    conv->created_at = now;
    conv->last_activity = now;
    conv->active = true;

    // Copy to output buffer
    if (conv_id_buf && buf_size > 0) {
        strncpy(conv_id_buf, conv->conversation_id, buf_size - 1);
        conv_id_buf[buf_size - 1] = '\0';
    }

    pthread_mutex_unlock(&cm->lock);
    return conv_id_buf;
}

Conversation* conversation_get(ConversationManager *cm, const char *conversation_id) {
    pthread_mutex_lock(&cm->lock);
    Conversation *conv = find_conversation(cm, conversation_id);
    pthread_mutex_unlock(&cm->lock);
    return conv;
}

int conversation_update_activity(ConversationManager *cm, const char *conversation_id) {
    pthread_mutex_lock(&cm->lock);
    Conversation *conv = find_conversation(cm, conversation_id);
    if (!conv) {
        pthread_mutex_unlock(&cm->lock);
        return -1;
    }
    conv->last_activity = time(NULL);
    pthread_mutex_unlock(&cm->lock);
    return 0;
}

int conversation_delete(ConversationManager *cm, const char *conversation_id) {
    pthread_mutex_lock(&cm->lock);
    Conversation *conv = find_conversation(cm, conversation_id);
    if (!conv) {
        pthread_mutex_unlock(&cm->lock);
        return -1;
    }
    conv->active = false;
    pthread_mutex_unlock(&cm->lock);
    return 0;
}

int conversation_list(ConversationManager *cm, char *buf, size_t bufsize, bool include_stale) {
    pthread_mutex_lock(&cm->lock);

    time_t now = time(NULL);
    int count = 0;
    size_t offset = 0;

    offset += snprintf(buf + offset, bufsize - offset, "[");

    for (int i = 0; i < cm->count && offset < bufsize - 500; i++) {
        Conversation *conv = &cm->conversations[i];
        if (!conv->active) continue;

        bool stale = is_conversation_stale(conv, now, cm->stale_threshold_seconds);
        if (stale && !include_stale) continue;

        if (count > 0) {
            offset += snprintf(buf + offset, bufsize - offset, ",");
        }

        // Build participants array
        char participants_json[512];
        size_t poff = 0;
        poff += snprintf(participants_json + poff, sizeof(participants_json) - poff, "[");
        for (int p = 0; p < conv->participant_count && poff < sizeof(participants_json) - 100; p++) {
            if (p > 0) poff += snprintf(participants_json + poff, sizeof(participants_json) - poff, ",");
            poff += snprintf(participants_json + poff, sizeof(participants_json) - poff,
                            "\"%s\"", conv->participants[p]);
        }
        snprintf(participants_json + poff, sizeof(participants_json) - poff, "]");

        offset += snprintf(buf + offset, bufsize - offset,
            "{\"conversation_id\":\"%s\",\"participants\":%s,"
            "\"created_at\":%ld,\"last_activity\":%ld,\"idle_seconds\":%ld,\"stale\":%s}",
            conv->conversation_id, participants_json,
            (long)conv->created_at, (long)conv->last_activity,
            (long)(now - conv->last_activity), stale ? "true" : "false");
        count++;
    }

    snprintf(buf + offset, bufsize - offset, "]");
    pthread_mutex_unlock(&cm->lock);
    return count;
}

int conversation_cleanup_stale(ConversationManager *cm) {
    pthread_mutex_lock(&cm->lock);

    time_t now = time(NULL);
    int cleaned = 0;

    for (int i = 0; i < cm->count; i++) {
        Conversation *conv = &cm->conversations[i];
        if (conv->active && is_conversation_stale(conv, now, cm->stale_threshold_seconds)) {
            conv->active = false;
            cleaned++;
        }
    }

    pthread_mutex_unlock(&cm->lock);
    return cleaned;
}

void conversation_stats(ConversationManager *cm, char *buf, size_t bufsize) {
    pthread_mutex_lock(&cm->lock);

    time_t now = time(NULL);
    int total = 0;
    int stale = 0;
    time_t oldest_created = 0;
    time_t most_idle = 0;

    for (int i = 0; i < cm->count; i++) {
        Conversation *conv = &cm->conversations[i];
        if (!conv->active) continue;

        total++;
        if (is_conversation_stale(conv, now, cm->stale_threshold_seconds)) {
            stale++;
        }

        if (oldest_created == 0 || conv->created_at < oldest_created) {
            oldest_created = conv->created_at;
        }
        if (most_idle == 0 || conv->last_activity < most_idle) {
            most_idle = conv->last_activity;
        }
    }

    snprintf(buf, bufsize,
        "{\"total_conversations\":%d,\"active\":%d,\"stale\":%d,"
        "\"oldest_created_at\":%ld,\"most_idle_at\":%ld,"
        "\"stale_threshold_seconds\":%d}",
        total, total - stale, stale,
        (long)oldest_created, (long)most_idle,
        cm->stale_threshold_seconds);

    pthread_mutex_unlock(&cm->lock);
}

void conversation_manager_shutdown(ConversationManager *cm) {
    cm->running = false;
}
