#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include "msgqueue.h"

// ============ UUID Generation ============

void generate_msg_id(char *buf, size_t size) {
    static const char hex[] = "0123456789abcdef";
    FILE *f = fopen("/dev/urandom", "r");
    if (f) {
        unsigned char bytes[6];
        fread(bytes, 1, 6, f);
        fclose(f);
        for (int i = 0; i < 6 && (size_t)(i*2+1) < size-1; i++) {
            buf[i*2] = hex[bytes[i] >> 4];
            buf[i*2+1] = hex[bytes[i] & 0xf];
        }
        buf[12] = '\0';
    } else {
        snprintf(buf, size, "%lx", (unsigned long)time(NULL));
    }
}

// ============ Hash function for dedup ============

static unsigned int hash_msg_id(const char *msg_id) {
    unsigned int hash = 5381;
    int c;
    while ((c = *msg_id++)) {
        hash = ((hash << 5) + hash) + c;
    }
    return hash % SEEN_HASH_SIZE;
}

// ============ Message Functions ============

Message* message_create(const char *from, const char *to, const char *payload,
                        const char *conv_id, const char *msg_type) {
    return message_create_full(from, to, payload, conv_id, msg_type, NULL, 0, DEFAULT_MAX_ATTEMPTS);
}

Message* message_create_full(const char *from, const char *to, const char *payload,
                             const char *conv_id, const char *msg_type, const char *trace_id,
                             int ttl_seconds, int max_attempts) {
    Message *msg = calloc(1, sizeof(Message));
    if (!msg) return NULL;

    generate_msg_id(msg->msg_id, sizeof(msg->msg_id));
    strncpy(msg->from, from ? from : "unknown", MAX_AGENT_NAME - 1);
    strncpy(msg->to, to ? to : "", MAX_AGENT_NAME - 1);

    if (payload) {
        msg->payload = strdup(payload);
    }
    if (conv_id && conv_id[0]) {
        msg->conversation_id = strdup(conv_id);
    }
    if (trace_id && trace_id[0]) {
        msg->trace_id = strdup(trace_id);
    }
    msg->message_type = strdup(msg_type ? msg_type : "request");
    msg->ts = time(NULL);
    msg->attempt = 0;
    msg->max_attempts = max_attempts > 0 ? max_attempts : DEFAULT_MAX_ATTEMPTS;
    msg->ttl_seconds = ttl_seconds;
    msg->expires_at = (ttl_seconds > 0) ? (msg->ts + ttl_seconds) : 0;
    msg->next = NULL;

    return msg;
}

Message* message_create_with_id(const char *msg_id, const char *from, const char *to,
                                const char *payload, const char *conv_id, const char *msg_type,
                                const char *trace_id, int ttl_seconds, int max_attempts) {
    Message *msg = calloc(1, sizeof(Message));
    if (!msg) return NULL;

    // Use provided msg_id or generate new one
    if (msg_id && msg_id[0]) {
        strncpy(msg->msg_id, msg_id, MAX_MSG_ID - 1);
    } else {
        generate_msg_id(msg->msg_id, sizeof(msg->msg_id));
    }
    strncpy(msg->from, from ? from : "unknown", MAX_AGENT_NAME - 1);
    strncpy(msg->to, to ? to : "", MAX_AGENT_NAME - 1);

    if (payload) {
        msg->payload = strdup(payload);
    }
    if (conv_id && conv_id[0]) {
        msg->conversation_id = strdup(conv_id);
    }
    if (trace_id && trace_id[0]) {
        msg->trace_id = strdup(trace_id);
    }
    msg->message_type = strdup(msg_type ? msg_type : "request");
    msg->ts = time(NULL);
    msg->attempt = 0;
    msg->max_attempts = max_attempts > 0 ? max_attempts : DEFAULT_MAX_ATTEMPTS;
    msg->ttl_seconds = ttl_seconds;
    msg->expires_at = (ttl_seconds > 0) ? (msg->ts + ttl_seconds) : 0;
    msg->next = NULL;

    return msg;
}

Message* message_clone(const Message *src) {
    if (!src) return NULL;

    Message *msg = calloc(1, sizeof(Message));
    if (!msg) return NULL;

    strncpy(msg->msg_id, src->msg_id, MAX_MSG_ID - 1);
    strncpy(msg->from, src->from, MAX_AGENT_NAME - 1);
    strncpy(msg->to, src->to, MAX_AGENT_NAME - 1);

    if (src->payload) msg->payload = strdup(src->payload);
    if (src->conversation_id) msg->conversation_id = strdup(src->conversation_id);
    if (src->message_type) msg->message_type = strdup(src->message_type);
    if (src->trace_id) msg->trace_id = strdup(src->trace_id);

    msg->ts = src->ts;
    msg->expires_at = src->expires_at;
    msg->attempt = src->attempt;
    msg->max_attempts = src->max_attempts;
    msg->ttl_seconds = src->ttl_seconds;
    msg->next = NULL;

    return msg;
}

void message_free(Message *msg) {
    if (!msg) return;
    free(msg->payload);
    free(msg->conversation_id);
    free(msg->message_type);
    free(msg->trace_id);
    free(msg);
}

void message_free_list(Message *msg) {
    while (msg) {
        Message *next = msg->next;
        message_free(msg);
        msg = next;
    }
}

bool message_is_expired(const Message *msg, time_t now) {
    if (!msg || msg->expires_at == 0) return false;
    return now >= msg->expires_at;
}

char* message_to_json(Message *msg) {
    char *buf = malloc(MAX_PAYLOAD_SIZE);
    if (!buf) return NULL;

    snprintf(buf, MAX_PAYLOAD_SIZE,
        "{\"msg_id\":\"%s\",\"from\":\"%s\",\"to\":\"%s\","
        "\"conversation_id\":%s%s%s,\"message_type\":\"%s\","
        "\"trace_id\":%s%s%s,"
        "\"ts\":%ld,\"attempt\":%d,\"max_attempts\":%d,"
        "\"ttl_seconds\":%d,\"expires_at\":%ld,"
        "\"payload\":%s}",
        msg->msg_id, msg->from, msg->to,
        msg->conversation_id ? "\"" : "",
        msg->conversation_id ? msg->conversation_id : "null",
        msg->conversation_id ? "\"" : "",
        msg->message_type ? msg->message_type : "request",
        msg->trace_id ? "\"" : "",
        msg->trace_id ? msg->trace_id : "null",
        msg->trace_id ? "\"" : "",
        (long)msg->ts, msg->attempt, msg->max_attempts,
        msg->ttl_seconds, (long)msg->expires_at,
        msg->payload ? msg->payload : "{}");

    return buf;
}

// ============ Queue Initialization ============

void msgqueue_init(MsgQueue *mq) {
    msgqueue_init_with_config(mq, DEFAULT_ACK_TIMEOUT, MAX_DEADLETTER_SIZE);
}

void msgqueue_init_with_config(MsgQueue *mq, int ack_timeout_seconds, int deadletter_max_size) {
    memset(mq, 0, sizeof(MsgQueue));
    mq->ack_timeout_seconds = ack_timeout_seconds > 0 ? ack_timeout_seconds : DEFAULT_ACK_TIMEOUT;
    mq->deadletter_max_size = deadletter_max_size > 0 ? deadletter_max_size : MAX_DEADLETTER_SIZE;
    pthread_mutex_init(&mq->lock, NULL);
}

void msgqueue_destroy(MsgQueue *mq) {
    pthread_mutex_lock(&mq->lock);

    for (int i = 0; i < mq->queue_count; i++) {
        Queue *q = &mq->queues[i];

        // Free queued messages
        message_free_list(q->head);

        // Free inflight records
        InflightRecord *rec = q->inflight_head;
        while (rec) {
            InflightRecord *next = rec->next;
            message_free(rec->msg);
            free(rec);
            rec = next;
        }

        // Free deadletter messages
        message_free_list(q->deadletter_head);
    }

    // Free retry heap messages
    for (int i = 0; i < mq->retry_heap_size; i++) {
        message_free(mq->retry_heap[i].msg);
    }

    pthread_mutex_unlock(&mq->lock);
    pthread_mutex_destroy(&mq->lock);
}

// ============ Internal Helpers ============

static Queue* find_or_create_queue(MsgQueue *mq, const char *agent) {
    // Find existing
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            return &mq->queues[i];
        }
    }
    // Create new
    if (mq->queue_count >= MAX_QUEUES) {
        return NULL;
    }
    Queue *q = &mq->queues[mq->queue_count++];
    memset(q, 0, sizeof(Queue));
    strncpy(q->agent, agent, MAX_AGENT_NAME - 1);
    return q;
}

static bool is_msg_id_seen(MsgQueue *mq, const char *to, const char *msg_id) {
    // Simple hash-based dedup (collision may occur, but acceptable)
    unsigned int idx = hash_msg_id(msg_id);
    if (strcmp(mq->seen_ids[idx].msg_id, msg_id) == 0) {
        // Check if still fresh (within 5 minutes)
        time_t now = time(NULL);
        if (now - mq->seen_ids[idx].seen_at < 300) {
            return true;
        }
    }
    return false;
}

static void mark_msg_id_seen(MsgQueue *mq, const char *msg_id) {
    unsigned int idx = hash_msg_id(msg_id);
    strncpy(mq->seen_ids[idx].msg_id, msg_id, MAX_MSG_ID - 1);
    mq->seen_ids[idx].seen_at = time(NULL);
}

static void deadletter_add(MsgQueue *mq, Queue *q, Message *msg) {
    if (!q || !msg) return;

    // Drop oldest if full
    while (q->deadletter_count >= mq->deadletter_max_size && q->deadletter_head) {
        Message *old = q->deadletter_head;
        q->deadletter_head = old->next;
        if (!q->deadletter_head) q->deadletter_tail = NULL;
        message_free(old);
        q->deadletter_count--;
    }

    // Append to deadletter
    msg->next = NULL;
    if (q->deadletter_tail) {
        q->deadletter_tail->next = msg;
        q->deadletter_tail = msg;
    } else {
        q->deadletter_head = q->deadletter_tail = msg;
    }
    q->deadletter_count++;
}

static InflightRecord* find_inflight(Queue *q, const char *msg_id) {
    InflightRecord *rec = q->inflight_head;
    while (rec) {
        if (strcmp(rec->msg->msg_id, msg_id) == 0) {
            return rec;
        }
        rec = rec->next;
    }
    return NULL;
}

static int remove_inflight(Queue *q, const char *msg_id, Message **out_msg) {
    InflightRecord **pp = &q->inflight_head;
    while (*pp) {
        if (strcmp((*pp)->msg->msg_id, msg_id) == 0) {
            InflightRecord *rec = *pp;
            *pp = rec->next;
            if (out_msg) {
                *out_msg = rec->msg;
            } else {
                message_free(rec->msg);
            }
            free(rec);
            q->inflight_count--;
            return 0;
        }
        pp = &(*pp)->next;
    }
    return -1; // Not found
}

// Heap operations for retry queue
static void heap_push(MsgQueue *mq, time_t ready_at, const char *agent, Message *msg) {
    if (mq->retry_heap_size >= MAX_RETRY_HEAP) {
        // Drop oldest (simple approach - just use the slot)
        message_free(mq->retry_heap[0].msg);
        mq->retry_heap_size--;
        memmove(&mq->retry_heap[0], &mq->retry_heap[1], mq->retry_heap_size * sizeof(RetryEntry));
    }

    // Add to end and bubble up
    int idx = mq->retry_heap_size++;
    mq->retry_heap[idx].ready_at = ready_at;
    strncpy(mq->retry_heap[idx].agent, agent, MAX_AGENT_NAME - 1);
    mq->retry_heap[idx].msg = msg;

    // Simple min-heap bubble-up
    while (idx > 0) {
        int parent = (idx - 1) / 2;
        if (mq->retry_heap[parent].ready_at <= mq->retry_heap[idx].ready_at) break;
        RetryEntry tmp = mq->retry_heap[parent];
        mq->retry_heap[parent] = mq->retry_heap[idx];
        mq->retry_heap[idx] = tmp;
        idx = parent;
    }
}

static int heap_pop(MsgQueue *mq, RetryEntry *out) {
    if (mq->retry_heap_size == 0) return -1;

    *out = mq->retry_heap[0];
    mq->retry_heap_size--;

    if (mq->retry_heap_size > 0) {
        mq->retry_heap[0] = mq->retry_heap[mq->retry_heap_size];

        // Bubble down
        int idx = 0;
        while (1) {
            int left = 2 * idx + 1;
            int right = 2 * idx + 2;
            int smallest = idx;

            if (left < mq->retry_heap_size &&
                mq->retry_heap[left].ready_at < mq->retry_heap[smallest].ready_at) {
                smallest = left;
            }
            if (right < mq->retry_heap_size &&
                mq->retry_heap[right].ready_at < mq->retry_heap[smallest].ready_at) {
                smallest = right;
            }

            if (smallest == idx) break;

            RetryEntry tmp = mq->retry_heap[idx];
            mq->retry_heap[idx] = mq->retry_heap[smallest];
            mq->retry_heap[smallest] = tmp;
            idx = smallest;
        }
    }

    return 0;
}

// ============ Core Functions ============

int msgqueue_send(MsgQueue *mq, const char *to, Message *msg) {
    pthread_mutex_lock(&mq->lock);

    time_t now = time(NULL);

    // Check expiry
    if (message_is_expired(msg, now)) {
        pthread_mutex_unlock(&mq->lock);
        return -1;
    }

    // Dedup by msg_id
    if (is_msg_id_seen(mq, to, msg->msg_id)) {
        pthread_mutex_unlock(&mq->lock);
        return 0; // Silently drop duplicate
    }
    mark_msg_id_seen(mq, msg->msg_id);

    Queue *q = find_or_create_queue(mq, to);
    if (!q) {
        pthread_mutex_unlock(&mq->lock);
        return -1;
    }

    // Drop oldest if full
    while (q->size >= MAX_QUEUE_SIZE && q->head) {
        Message *old = q->head;
        q->head = old->next;
        if (!q->head) q->tail = NULL;
        message_free(old);
        q->size--;
    }

    // Append
    msg->next = NULL;
    if (q->tail) {
        q->tail->next = msg;
        q->tail = msg;
    } else {
        q->head = q->tail = msg;
    }
    q->size++;

    pthread_mutex_unlock(&mq->lock);
    return 0;
}

Message* msgqueue_recv(MsgQueue *mq, const char *agent) {
    return msgqueue_recv_filtered(mq, agent, NULL);
}

Message* msgqueue_recv_filtered(MsgQueue *mq, const char *agent, const char *conversation_id) {
    pthread_mutex_lock(&mq->lock);

    Queue *q = NULL;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            q = &mq->queues[i];
            break;
        }
    }

    if (!q || !q->head) {
        pthread_mutex_unlock(&mq->lock);
        return NULL;
    }

    Message *result_head = NULL;
    Message *result_tail = NULL;
    Message *kept_head = NULL;
    Message *kept_tail = NULL;

    Message *m = q->head;
    while (m) {
        Message *next = m->next;
        m->next = NULL;

        bool match = !conversation_id || !conversation_id[0] ||
                     (m->conversation_id && strcmp(m->conversation_id, conversation_id) == 0);

        if (match) {
            // Add to result list
            if (result_tail) {
                result_tail->next = m;
                result_tail = m;
            } else {
                result_head = result_tail = m;
            }
        } else {
            // Keep in queue
            if (kept_tail) {
                kept_tail->next = m;
                kept_tail = m;
            } else {
                kept_head = kept_tail = m;
            }
        }

        m = next;
    }

    // Update queue
    q->head = kept_head;
    q->tail = kept_tail;
    q->size = 0;
    for (Message *p = kept_head; p; p = p->next) {
        q->size++;
    }

    pthread_mutex_unlock(&mq->lock);
    return result_head;
}

int msgqueue_peek(MsgQueue *mq, const char *agent) {
    pthread_mutex_lock(&mq->lock);
    int size = 0;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            size = mq->queues[i].size;
            break;
        }
    }
    pthread_mutex_unlock(&mq->lock);
    return size;
}

void msgqueue_stats(MsgQueue *mq, char *buf, size_t bufsize) {
    pthread_mutex_lock(&mq->lock);

    int total_queued = 0;
    int total_inflight = 0;
    int total_deadletter = 0;

    size_t offset = 0;
    offset += snprintf(buf + offset, bufsize - offset,
        "{\"total_agents\":%d,\"queues\":{", mq->queue_count);

    for (int i = 0; i < mq->queue_count && offset < bufsize - 200; i++) {
        Queue *q = &mq->queues[i];
        total_queued += q->size;
        total_inflight += q->inflight_count;
        total_deadletter += q->deadletter_count;

        if (i > 0) offset += snprintf(buf + offset, bufsize - offset, ",");
        offset += snprintf(buf + offset, bufsize - offset,
            "\"%s\":{\"queued\":%d,\"inflight\":%d,\"deadletter\":%d}",
            q->agent, q->size, q->inflight_count, q->deadletter_count);
    }

    snprintf(buf + offset, bufsize - offset,
        "},\"total_queued\":%d,\"total_inflight\":%d,\"total_deadletter\":%d,\"retry_heap_size\":%d}",
        total_queued, total_inflight, total_deadletter, mq->retry_heap_size);

    pthread_mutex_unlock(&mq->lock);
}

// ============ ACK Mode Functions ============

int msgqueue_claim(MsgQueue *mq, const char *agent, const char *conversation_id,
                   int max_items, Message **out_msgs, int *out_count) {
    if (max_items <= 0) max_items = 100;

    pthread_mutex_lock(&mq->lock);

    time_t now = time(NULL);
    *out_count = 0;
    *out_msgs = NULL;

    Queue *q = NULL;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            q = &mq->queues[i];
            break;
        }
    }

    if (!q || !q->head) {
        pthread_mutex_unlock(&mq->lock);
        return 0;
    }

    Message *claimed_head = NULL;
    Message *claimed_tail = NULL;
    Message *kept_head = NULL;
    Message *kept_tail = NULL;
    int claimed_count = 0;

    Message *m = q->head;
    while (m) {
        Message *next = m->next;
        m->next = NULL;

        // Check expiry
        if (message_is_expired(m, now)) {
            deadletter_add(mq, q, m);
            m = next;
            continue;
        }

        // Check conversation filter
        bool match = !conversation_id || !conversation_id[0] ||
                     (m->conversation_id && strcmp(m->conversation_id, conversation_id) == 0);

        if (match && claimed_count < max_items && q->inflight_count < MAX_INFLIGHT_PER_AGENT) {
            // Create inflight record
            InflightRecord *rec = calloc(1, sizeof(InflightRecord));
            if (rec) {
                rec->msg = m;
                rec->delivered_at = now;
                rec->ack_deadline = now + mq->ack_timeout_seconds;
                rec->next_attempt_at = rec->ack_deadline;
                rec->next = q->inflight_head;
                q->inflight_head = rec;
                q->inflight_count++;

                // Add to claimed result (clone for caller)
                Message *clone = message_clone(m);
                if (clone) {
                    if (claimed_tail) {
                        claimed_tail->next = clone;
                        claimed_tail = clone;
                    } else {
                        claimed_head = claimed_tail = clone;
                    }
                    claimed_count++;
                }
            } else {
                // OOM, keep in queue
                if (kept_tail) {
                    kept_tail->next = m;
                    kept_tail = m;
                } else {
                    kept_head = kept_tail = m;
                }
            }
        } else {
            // Keep in queue
            if (kept_tail) {
                kept_tail->next = m;
                kept_tail = m;
            } else {
                kept_head = kept_tail = m;
            }
        }

        m = next;
    }

    // Update queue
    q->head = kept_head;
    q->tail = kept_tail;
    q->size = 0;
    for (Message *p = kept_head; p; p = p->next) {
        q->size++;
    }

    *out_msgs = claimed_head;
    *out_count = claimed_count;

    pthread_mutex_unlock(&mq->lock);
    return 0;
}

int msgqueue_ack(MsgQueue *mq, const char *agent, const char **msg_ids, int id_count,
                 int *acked, char *missing_buf, size_t missing_buf_size) {
    pthread_mutex_lock(&mq->lock);

    *acked = 0;
    size_t missing_offset = 0;
    missing_buf[0] = '\0';

    Queue *q = NULL;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            q = &mq->queues[i];
            break;
        }
    }

    if (!q) {
        // No queue, all missing
        for (int i = 0; i < id_count && missing_offset < missing_buf_size - 50; i++) {
            if (i > 0) missing_offset += snprintf(missing_buf + missing_offset,
                                                   missing_buf_size - missing_offset, ",");
            missing_offset += snprintf(missing_buf + missing_offset,
                                        missing_buf_size - missing_offset, "\"%s\"", msg_ids[i]);
        }
        pthread_mutex_unlock(&mq->lock);
        return 0;
    }

    for (int i = 0; i < id_count; i++) {
        Message *msg = NULL;
        if (remove_inflight(q, msg_ids[i], &msg) == 0) {
            message_free(msg);
            (*acked)++;
        } else {
            if (missing_offset > 0 && missing_offset < missing_buf_size - 50) {
                missing_offset += snprintf(missing_buf + missing_offset,
                                           missing_buf_size - missing_offset, ",");
            }
            if (missing_offset < missing_buf_size - 50) {
                missing_offset += snprintf(missing_buf + missing_offset,
                                           missing_buf_size - missing_offset, "\"%s\"", msg_ids[i]);
            }
        }
    }

    pthread_mutex_unlock(&mq->lock);
    return 0;
}

int msgqueue_retry_tick(MsgQueue *mq) {
    pthread_mutex_lock(&mq->lock);

    time_t now = time(NULL);
    int requeued = 0;
    int deadlettered = 0;
    int expired = 0;
    int retry_due = 0;

    // Process inflight timeouts
    for (int i = 0; i < mq->queue_count; i++) {
        Queue *q = &mq->queues[i];
        InflightRecord **pp = &q->inflight_head;

        while (*pp) {
            InflightRecord *rec = *pp;
            Message *msg = rec->msg;

            // Check expiry
            if (message_is_expired(msg, now)) {
                *pp = rec->next;
                q->inflight_count--;
                deadletter_add(mq, q, msg);
                free(rec);
                expired++;
                continue;
            }

            // Check ACK timeout
            if (now >= rec->next_attempt_at) {
                *pp = rec->next;
                q->inflight_count--;

                int next_attempt = msg->attempt + 1;
                if (next_attempt >= msg->max_attempts) {
                    deadletter_add(mq, q, msg);
                    free(rec);
                    deadlettered++;
                    continue;
                }

                // Schedule retry with exponential backoff
                Message *retry_msg = message_clone(msg);
                if (retry_msg) {
                    retry_msg->attempt = next_attempt;
                    int backoff = 1 << (next_attempt - 1); // 1, 2, 4, 8, ...
                    if (backoff > 60) backoff = 60;
                    time_t ready_at = now + backoff;
                    heap_push(mq, ready_at, q->agent, retry_msg);
                    requeued++;
                }

                message_free(msg);
                free(rec);
                continue;
            }

            pp = &rec->next;
        }
    }

    // Process due retries from heap
    while (mq->retry_heap_size > 0 && mq->retry_heap[0].ready_at <= now) {
        RetryEntry entry;
        if (heap_pop(mq, &entry) != 0) break;

        Message *msg = entry.msg;

        // Check expiry
        if (message_is_expired(msg, now)) {
            Queue *q = find_or_create_queue(mq, entry.agent);
            if (q) {
                deadletter_add(mq, q, msg);
            } else {
                message_free(msg);
            }
            expired++;
            continue;
        }

        // Requeue (bypass dedup since it's a retry)
        Queue *q = find_or_create_queue(mq, entry.agent);
        if (q) {
            // Prepend to queue head for priority
            msg->next = q->head;
            q->head = msg;
            if (!q->tail) q->tail = msg;
            q->size++;
            retry_due++;
        } else {
            message_free(msg);
        }
    }

    pthread_mutex_unlock(&mq->lock);
    return requeued + retry_due + deadlettered + expired;
}

int msgqueue_inflight_count(MsgQueue *mq, const char *agent) {
    pthread_mutex_lock(&mq->lock);
    int count = 0;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            count = mq->queues[i].inflight_count;
            break;
        }
    }
    pthread_mutex_unlock(&mq->lock);
    return count;
}

int msgqueue_deadletter_list(MsgQueue *mq, const char *agent, char *buf, size_t bufsize, int max_items) {
    pthread_mutex_lock(&mq->lock);

    Queue *q = NULL;
    for (int i = 0; i < mq->queue_count; i++) {
        if (strcmp(mq->queues[i].agent, agent) == 0) {
            q = &mq->queues[i];
            break;
        }
    }

    size_t offset = 0;
    offset += snprintf(buf + offset, bufsize - offset, "[");

    int count = 0;
    if (q && q->deadletter_head) {
        Message *m = q->deadletter_head;
        while (m && count < max_items && offset < bufsize - 200) {
            if (count > 0) {
                offset += snprintf(buf + offset, bufsize - offset, ",");
            }
            char *msg_json = message_to_json(m);
            if (msg_json) {
                offset += snprintf(buf + offset, bufsize - offset, "%s", msg_json);
                free(msg_json);
            }
            count++;
            m = m->next;
        }
    }

    snprintf(buf + offset, bufsize - offset, "]");

    pthread_mutex_unlock(&mq->lock);
    return count;
}
