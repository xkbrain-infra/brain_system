#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "delayed_queue.h"

// ============ Heap Operations ============

static void heap_swap(DelayedQueue *dq, int i, int j) {
    DelayedEntry tmp = dq->heap[i];
    dq->heap[i] = dq->heap[j];
    dq->heap[j] = tmp;
}

static void heap_bubble_up(DelayedQueue *dq, int idx) {
    while (idx > 0) {
        int parent = (idx - 1) / 2;
        if (dq->heap[parent].send_at <= dq->heap[idx].send_at) break;
        heap_swap(dq, parent, idx);
        idx = parent;
    }
}

static void heap_bubble_down(DelayedQueue *dq, int idx) {
    while (1) {
        int left = 2 * idx + 1;
        int right = 2 * idx + 2;
        int smallest = idx;

        if (left < dq->count && dq->heap[left].send_at < dq->heap[smallest].send_at) {
            smallest = left;
        }
        if (right < dq->count && dq->heap[right].send_at < dq->heap[smallest].send_at) {
            smallest = right;
        }

        if (smallest == idx) break;

        heap_swap(dq, idx, smallest);
        idx = smallest;
    }
}

static int heap_push(DelayedQueue *dq, time_t send_at, Message *msg) {
    if (dq->count >= MAX_DELAYED_ENTRIES) {
        return -1; // Full
    }

    int idx = dq->count++;
    dq->heap[idx].send_at = send_at;
    dq->heap[idx].msg = msg;
    heap_bubble_up(dq, idx);
    return 0;
}

static int heap_pop(DelayedQueue *dq, DelayedEntry *out) {
    if (dq->count == 0) return -1;

    *out = dq->heap[0];
    dq->count--;

    if (dq->count > 0) {
        dq->heap[0] = dq->heap[dq->count];
        heap_bubble_down(dq, 0);
    }

    return 0;
}

// ============ Public API ============

void delayed_queue_init(DelayedQueue *dq, MsgQueue *mq) {
    memset(dq, 0, sizeof(DelayedQueue));
    dq->msgqueue = mq;
    dq->on_deliver = NULL;
    dq->running = true;
    pthread_mutex_init(&dq->lock, NULL);
}

void delayed_queue_set_deliver_cb(DelayedQueue *dq, delayed_deliver_cb cb) {
    dq->on_deliver = cb;
}

void delayed_queue_destroy(DelayedQueue *dq) {
    pthread_mutex_lock(&dq->lock);

    // Free all pending messages
    for (int i = 0; i < dq->count; i++) {
        message_free(dq->heap[i].msg);
    }
    dq->count = 0;

    pthread_mutex_unlock(&dq->lock);
    pthread_mutex_destroy(&dq->lock);
}

time_t delayed_queue_schedule(DelayedQueue *dq, Message *msg, int delay_seconds) {
    if (!msg || delay_seconds < 0 || delay_seconds > 86400) {
        return 0;
    }

    pthread_mutex_lock(&dq->lock);

    time_t now = time(NULL);
    time_t send_at = now + delay_seconds;

    if (heap_push(dq, send_at, msg) != 0) {
        pthread_mutex_unlock(&dq->lock);
        return 0; // Queue full
    }

    pthread_mutex_unlock(&dq->lock);
    return send_at;
}

int delayed_queue_tick(DelayedQueue *dq) {
    if (!dq->running) return 0;

    pthread_mutex_lock(&dq->lock);

    time_t now = time(NULL);
    int delivered = 0;

    while (dq->count > 0 && dq->heap[0].send_at <= now) {
        DelayedEntry entry;
        if (heap_pop(dq, &entry) != 0) break;

        Message *msg = entry.msg;

        // Check if message expired
        if (message_is_expired(msg, now)) {
            message_free(msg);
            continue;
        }

        // Deliver to target queue
        if (dq->msgqueue) {
            msgqueue_send(dq->msgqueue, msg->to, msg);
            delivered++;

            // Notify target agent about the delivered message
            if (dq->on_deliver) {
                dq->on_deliver(msg->to, msg->msg_id, msg->from, msg);
            }
        } else {
            message_free(msg);
        }
    }

    pthread_mutex_unlock(&dq->lock);
    return delivered;
}

int delayed_queue_size(DelayedQueue *dq) {
    pthread_mutex_lock(&dq->lock);
    int count = dq->count;
    pthread_mutex_unlock(&dq->lock);
    return count;
}

int delayed_queue_peek_next(DelayedQueue *dq, time_t *send_at, char *msg_id, size_t msg_id_size) {
    pthread_mutex_lock(&dq->lock);

    if (dq->count == 0) {
        pthread_mutex_unlock(&dq->lock);
        return -1;
    }

    if (send_at) *send_at = dq->heap[0].send_at;
    if (msg_id && msg_id_size > 0) {
        strncpy(msg_id, dq->heap[0].msg->msg_id, msg_id_size - 1);
        msg_id[msg_id_size - 1] = '\0';
    }

    pthread_mutex_unlock(&dq->lock);
    return 0;
}

void delayed_queue_stats(DelayedQueue *dq, char *buf, size_t bufsize) {
    pthread_mutex_lock(&dq->lock);

    time_t next_send = 0;
    char next_msg_id[MAX_MSG_ID] = "";

    if (dq->count > 0) {
        next_send = dq->heap[0].send_at;
        strncpy(next_msg_id, dq->heap[0].msg->msg_id, sizeof(next_msg_id) - 1);
    }

    snprintf(buf, bufsize,
        "{\"total_scheduled\":%d,\"next_delivery_at\":%ld,"
        "\"next_msg_id\":\"%s\",\"scheduler_running\":%s}",
        dq->count, (long)next_send, next_msg_id,
        dq->running ? "true" : "false");

    pthread_mutex_unlock(&dq->lock);
}

void delayed_queue_shutdown(DelayedQueue *dq) {
    dq->running = false;
}
