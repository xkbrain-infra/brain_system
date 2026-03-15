#ifndef CONVERSATION_H
#define CONVERSATION_H

#include <pthread.h>
#include <stdbool.h>
#include <time.h>

#define MAX_CONVERSATIONS 1000
#define MAX_CONVERSATION_ID 32
#define MAX_PARTICIPANTS 8
#define MAX_PARTICIPANT_NAME 64
#define MAX_CONV_METADATA_SIZE 1024
#define DEFAULT_STALE_HOURS 24

typedef struct {
    char conversation_id[MAX_CONVERSATION_ID];
    char participants[MAX_PARTICIPANTS][MAX_PARTICIPANT_NAME];
    int participant_count;
    char metadata[MAX_CONV_METADATA_SIZE];
    time_t created_at;
    time_t last_activity;
    bool active;
} Conversation;

typedef struct {
    Conversation conversations[MAX_CONVERSATIONS];
    int count;
    int stale_threshold_seconds;
    pthread_mutex_t lock;
    volatile bool running;
} ConversationManager;

// Initialization
void conversation_manager_init(ConversationManager *cm);
void conversation_manager_init_with_config(ConversationManager *cm, int stale_hours);
void conversation_manager_destroy(ConversationManager *cm);

// Create a new conversation
// participants: comma-separated list of agent names (e.g., "claude,codex")
// Returns: conversation_id (written to conv_id_buf), or NULL on error
char* conversation_create(ConversationManager *cm, const char *participants,
                          const char *metadata, char *conv_id_buf, size_t buf_size);

// Get conversation by ID
Conversation* conversation_get(ConversationManager *cm, const char *conversation_id);

// Update last_activity timestamp
int conversation_update_activity(ConversationManager *cm, const char *conversation_id);

// Delete conversation
int conversation_delete(ConversationManager *cm, const char *conversation_id);

// List all conversations
int conversation_list(ConversationManager *cm, char *buf, size_t bufsize, bool include_stale);

// Cleanup stale conversations (should be called periodically)
// Returns: number of conversations cleaned up
int conversation_cleanup_stale(ConversationManager *cm);

// Statistics
void conversation_stats(ConversationManager *cm, char *buf, size_t bufsize);

// Shutdown
void conversation_manager_shutdown(ConversationManager *cm);

#endif
