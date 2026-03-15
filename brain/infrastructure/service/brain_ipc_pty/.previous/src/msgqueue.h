#ifndef MSGQUEUE_H
#define MSGQUEUE_H

#include <pthread.h>
#include <stdbool.h>
#include <time.h>

#define MAX_QUEUES 256
#define MAX_QUEUE_SIZE 1000
#define MAX_INFLIGHT_PER_AGENT 100
#define MAX_DEADLETTER_SIZE 1000
#define MAX_RETRY_HEAP 10000
#define MAX_MSG_ID 32
#define MAX_AGENT_NAME 64
#define MAX_PAYLOAD_SIZE 65536
#define DEFAULT_ACK_TIMEOUT 60
#define DEFAULT_MAX_ATTEMPTS 5

// Message state machine: queued -> inflight -> acked/retry/deadletter
typedef enum {
    MSG_STATE_QUEUED,
    MSG_STATE_INFLIGHT,
    MSG_STATE_ACKED,
    MSG_STATE_RETRY_WAIT,
    MSG_STATE_EXPIRED,
    MSG_STATE_DEADLETTER
} MessageState;

typedef struct Message {
    char msg_id[MAX_MSG_ID];
    char from[MAX_AGENT_NAME];
    char to[MAX_AGENT_NAME];
    char *payload;              // JSON string, heap allocated
    char *conversation_id;      // Optional, heap allocated
    char *message_type;         // request/response/final
    char *trace_id;             // Optional, heap allocated
    time_t ts;                  // Creation timestamp
    time_t expires_at;          // TTL expiry (0 = no expiry)
    int attempt;                // Current attempt (0-based)
    int max_attempts;           // Max attempts before deadletter
    int ttl_seconds;            // Time-to-live (0 = no TTL)
    struct Message *next;       // For linked list
} Message;

// Inflight record - tracks claimed messages awaiting ACK
typedef struct InflightRecord {
    Message *msg;
    time_t delivered_at;
    time_t ack_deadline;
    time_t next_attempt_at;
    struct InflightRecord *next;
} InflightRecord;

// Retry heap entry
typedef struct RetryEntry {
    time_t ready_at;
    char agent[MAX_AGENT_NAME];
    Message *msg;
} RetryEntry;

// Per-agent queue
typedef struct {
    char agent[MAX_AGENT_NAME];
    Message *head;
    Message *tail;
    int size;
    // Inflight map (msg_id -> InflightRecord)
    InflightRecord *inflight_head;
    int inflight_count;
    // Deadletter queue
    Message *deadletter_head;
    Message *deadletter_tail;
    int deadletter_count;
} Queue;

// Seen message IDs for dedup (simple hash set approximation)
#define SEEN_HASH_SIZE 4096
typedef struct {
    char msg_id[MAX_MSG_ID];
    time_t seen_at;
} SeenEntry;

typedef struct {
    Queue queues[MAX_QUEUES];
    int queue_count;
    // Global retry heap
    RetryEntry retry_heap[MAX_RETRY_HEAP];
    int retry_heap_size;
    // Global dedup set
    SeenEntry seen_ids[SEEN_HASH_SIZE];
    // Config
    int ack_timeout_seconds;
    int deadletter_max_size;
    pthread_mutex_t lock;
} MsgQueue;

// Core functions
void msgqueue_init(MsgQueue *mq);
void msgqueue_init_with_config(MsgQueue *mq, int ack_timeout_seconds, int deadletter_max_size);
void msgqueue_destroy(MsgQueue *mq);
int msgqueue_send(MsgQueue *mq, const char *to, Message *msg);
Message* msgqueue_recv(MsgQueue *mq, const char *agent);
Message* msgqueue_recv_filtered(MsgQueue *mq, const char *agent, const char *conversation_id);
int msgqueue_peek(MsgQueue *mq, const char *agent);
void msgqueue_stats(MsgQueue *mq, char *buf, size_t bufsize);

// ACK mode functions (v2 reliability)
int msgqueue_claim(MsgQueue *mq, const char *agent, const char *conversation_id,
                   int max_items, Message **out_msgs, int *out_count);
int msgqueue_ack(MsgQueue *mq, const char *agent, const char **msg_ids, int id_count,
                 int *acked, char *missing_buf, size_t missing_buf_size);
int msgqueue_retry_tick(MsgQueue *mq);
int msgqueue_inflight_count(MsgQueue *mq, const char *agent);
int msgqueue_deadletter_list(MsgQueue *mq, const char *agent, char *buf, size_t bufsize, int max_items);

// Message functions
Message* message_create(const char *from, const char *to, const char *payload,
                        const char *conv_id, const char *msg_type);
Message* message_create_full(const char *from, const char *to, const char *payload,
                             const char *conv_id, const char *msg_type, const char *trace_id,
                             int ttl_seconds, int max_attempts);
Message* message_create_with_id(const char *msg_id, const char *from, const char *to,
                                const char *payload, const char *conv_id, const char *msg_type,
                                const char *trace_id, int ttl_seconds, int max_attempts);
Message* message_clone(const Message *src);
void message_free(Message *msg);
void message_free_list(Message *msg);
char* message_to_json(Message *msg);
bool message_is_expired(const Message *msg, time_t now);

// UUID generation
void generate_msg_id(char *buf, size_t size);

#endif
