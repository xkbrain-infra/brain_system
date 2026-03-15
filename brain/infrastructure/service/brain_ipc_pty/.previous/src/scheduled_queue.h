/**
 * scheduled_queue.h - Cron-like scheduler for Agent IPC
 *
 * Supports:
 * - Cron expressions: "0 * * * *" (every hour)
 * - Periodic intervals: every N seconds
 * - One-shot scheduled tasks at specific time
 */

#ifndef SCHEDULED_QUEUE_H
#define SCHEDULED_QUEUE_H

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#define SCHED_MAX_TASKS 256
#define SCHED_TASK_ID_LEN 64
#define SCHED_AGENT_NAME_LEN 64
#define SCHED_PAYLOAD_LEN 4096
#define SCHED_CRON_EXPR_LEN 64

typedef enum {
    SCHED_TYPE_CRON,
    SCHED_TYPE_PERIODIC,
    SCHED_TYPE_ONCE
} sched_task_type_t;

typedef struct {
    uint8_t minute[60];   // 0-59
    uint8_t hour[24];     // 0-23
    uint8_t day[32];      // 1-31 (index 0 unused)
    uint8_t month[13];    // 1-12 (index 0 unused)
    uint8_t weekday[7];   // 0-6 (0=Sunday)
} cron_schedule_t;

typedef struct {
    char task_id[SCHED_TASK_ID_LEN];
    sched_task_type_t task_type;
    char to[SCHED_AGENT_NAME_LEN];
    char payload[SCHED_PAYLOAD_LEN];
    char message_type[32];

    // Cron
    char cron_expr[SCHED_CRON_EXPR_LEN];
    cron_schedule_t cron_parsed;

    // Periodic
    int interval_seconds;
    time_t last_run;

    // Once
    time_t run_at;

    // Common
    bool enabled;
    time_t created_at;
    int run_count;
    int max_runs;  // -1 = unlimited

    bool in_use;
} sched_task_t;

typedef struct {
    sched_task_t tasks[SCHED_MAX_TASKS];
    int task_count;
    pthread_mutex_t lock;
    pthread_t scheduler_thread;
    bool running;
    int last_cron_minute;

    // Callback to send message (set by brain_ipc)
    void (*send_callback)(const char *to, const char *payload, const char *msg_type);
} scheduled_queue_t;

// Initialize scheduler
int sched_init(scheduled_queue_t *sq, void (*send_cb)(const char*, const char*, const char*));

// Shutdown scheduler
void sched_shutdown(scheduled_queue_t *sq);

// Add cron task: "0 * * * *" = every hour at minute 0
int sched_add_cron(scheduled_queue_t *sq, const char *task_id, const char *cron_expr,
                   const char *to, const char *payload, const char *msg_type, int max_runs);

// Add periodic task: every N seconds
int sched_add_periodic(scheduled_queue_t *sq, const char *task_id, int interval_seconds,
                       const char *to, const char *payload, const char *msg_type,
                       int max_runs, bool run_immediately);

// Add one-shot task at specific time
int sched_add_once(scheduled_queue_t *sq, const char *task_id, time_t run_at,
                   const char *to, const char *payload, const char *msg_type);

// Remove task
int sched_remove(scheduled_queue_t *sq, const char *task_id);

// Enable/disable task
int sched_enable(scheduled_queue_t *sq, const char *task_id, bool enabled);

// List tasks (returns JSON string, caller must free)
char *sched_list_tasks(scheduled_queue_t *sq);

// Get stats (returns JSON string, caller must free)
char *sched_stats(scheduled_queue_t *sq);

// Parse cron expression
int parse_cron(const char *expr, cron_schedule_t *out);

#endif // SCHEDULED_QUEUE_H
