#ifndef DELAYED_QUEUE_H
#define DELAYED_QUEUE_H

#include <pthread.h>
#include <stdbool.h>
#include <time.h>
#include "msgqueue.h"

#define MAX_DELAYED_ENTRIES 10000

// Delayed message entry (min-heap by send_at)
typedef struct {
    time_t send_at;
    Message *msg;
} DelayedEntry;

// Callback invoked after a delayed message is delivered to the msgqueue.
// Parameters: to (resolved target), msg_id, from, message pointer.
typedef void (*delayed_deliver_cb)(const char *to, const char *msg_id, const char *from, const Message *msg);

typedef struct {
    DelayedEntry heap[MAX_DELAYED_ENTRIES];
    int count;
    MsgQueue *msgqueue;  // Target queue for delivery
    delayed_deliver_cb on_deliver;  // Post-delivery notification callback
    pthread_mutex_t lock;
    volatile bool running;
} DelayedQueue;

// Initialization
void delayed_queue_init(DelayedQueue *dq, MsgQueue *mq);
void delayed_queue_set_deliver_cb(DelayedQueue *dq, delayed_deliver_cb cb);
void delayed_queue_destroy(DelayedQueue *dq);

// Schedule a message for delayed delivery
// Returns: scheduled send_at timestamp, or 0 on error
time_t delayed_queue_schedule(DelayedQueue *dq, Message *msg, int delay_seconds);

// Process due messages and deliver to msgqueue
// Should be called periodically (e.g., every second)
// Returns: number of messages delivered
int delayed_queue_tick(DelayedQueue *dq);

// Get count of scheduled messages
int delayed_queue_size(DelayedQueue *dq);

// Peek at next scheduled message (without removing)
// Returns 0 on success, -1 if empty
int delayed_queue_peek_next(DelayedQueue *dq, time_t *send_at, char *msg_id, size_t msg_id_size);

// Statistics
void delayed_queue_stats(DelayedQueue *dq, char *buf, size_t bufsize);

// Shutdown flag
void delayed_queue_shutdown(DelayedQueue *dq);

#endif
