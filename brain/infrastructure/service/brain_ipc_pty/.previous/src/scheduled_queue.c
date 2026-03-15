/**
 * scheduled_queue.c - Cron-like scheduler for Agent IPC
 */

#include "scheduled_queue.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <ctype.h>

// Parse a single cron field into bit array
// Supports: *, */N, N, N-M, N,M,O
static int parse_cron_field(const char *field, uint8_t *out, int min_val, int max_val) {
    char buf[64];
    strncpy(buf, field, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    // Clear output
    memset(out, 0, (max_val + 1) * sizeof(uint8_t));

    char *token = strtok(buf, ",");
    while (token) {
        // Trim whitespace
        while (*token && isspace(*token)) token++;
        char *end = token + strlen(token) - 1;
        while (end > token && isspace(*end)) *end-- = '\0';

        if (strcmp(token, "*") == 0) {
            // All values
            for (int i = min_val; i <= max_val; i++) {
                out[i] = 1;
            }
        } else if (strncmp(token, "*/", 2) == 0) {
            // Step: */N
            int step = atoi(token + 2);
            if (step <= 0) step = 1;
            for (int i = min_val; i <= max_val; i += step) {
                out[i] = 1;
            }
        } else if (strchr(token, '-')) {
            // Range: N-M
            int start, end_val;
            if (sscanf(token, "%d-%d", &start, &end_val) == 2) {
                for (int i = start; i <= end_val && i <= max_val; i++) {
                    if (i >= min_val) out[i] = 1;
                }
            }
        } else {
            // Single value
            int val = atoi(token);
            if (val >= min_val && val <= max_val) {
                out[val] = 1;
            }
        }

        token = strtok(NULL, ",");
    }

    return 0;
}

int parse_cron(const char *expr, cron_schedule_t *out) {
    char buf[128];
    strncpy(buf, expr, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *fields[5];
    int field_count = 0;
    char *p = buf;

    // Split by whitespace
    while (*p && field_count < 5) {
        while (*p && isspace(*p)) p++;
        if (!*p) break;

        fields[field_count++] = p;

        while (*p && !isspace(*p)) p++;
        if (*p) *p++ = '\0';
    }

    if (field_count != 5) {
        return -1;  // Invalid cron expression
    }

    memset(out, 0, sizeof(*out));

    parse_cron_field(fields[0], out->minute, 0, 59);
    parse_cron_field(fields[1], out->hour, 0, 23);
    parse_cron_field(fields[2], out->day, 1, 31);
    parse_cron_field(fields[3], out->month, 1, 12);
    parse_cron_field(fields[4], out->weekday, 0, 6);

    return 0;
}

static bool cron_matches(const cron_schedule_t *cron, struct tm *tm) {
    // tm_wday: 0=Sunday, which matches our weekday array
    return cron->minute[tm->tm_min] &&
           cron->hour[tm->tm_hour] &&
           cron->day[tm->tm_mday] &&
           cron->month[tm->tm_mon + 1] &&
           cron->weekday[tm->tm_wday];
}

static sched_task_t *find_task(scheduled_queue_t *sq, const char *task_id) {
    for (int i = 0; i < SCHED_MAX_TASKS; i++) {
        if (sq->tasks[i].in_use && strcmp(sq->tasks[i].task_id, task_id) == 0) {
            return &sq->tasks[i];
        }
    }
    return NULL;
}

static sched_task_t *alloc_task(scheduled_queue_t *sq) {
    for (int i = 0; i < SCHED_MAX_TASKS; i++) {
        if (!sq->tasks[i].in_use) {
            memset(&sq->tasks[i], 0, sizeof(sched_task_t));
            sq->tasks[i].in_use = true;
            sq->task_count++;
            return &sq->tasks[i];
        }
    }
    return NULL;
}

static void execute_task(scheduled_queue_t *sq, sched_task_t *task, time_t now) {
    if (!sq->send_callback) return;

    // Build payload with scheduling metadata
    char full_payload[SCHED_PAYLOAD_LEN + 256];
    // Simple JSON merge - inject _scheduled field
    if (task->payload[0] == '{') {
        // Insert _scheduled before closing brace
        size_t len = strlen(task->payload);
        if (len > 1 && task->payload[len-1] == '}') {
            snprintf(full_payload, sizeof(full_payload),
                "%.*s,\"_scheduled\":{\"task_id\":\"%s\",\"task_type\":\"%s\",\"run_count\":%d}}",
                (int)(len - 1), task->payload,
                task->task_id,
                task->task_type == SCHED_TYPE_CRON ? "cron" :
                task->task_type == SCHED_TYPE_PERIODIC ? "periodic" : "once",
                task->run_count + 1);
        } else {
            strncpy(full_payload, task->payload, sizeof(full_payload));
        }
    } else {
        strncpy(full_payload, task->payload, sizeof(full_payload));
    }

    // Send message
    sq->send_callback(task->to, full_payload, task->message_type);

    // Update task state
    task->run_count++;
    task->last_run = now;

    // Disable if max runs reached
    if (task->max_runs > 0 && task->run_count >= task->max_runs) {
        task->enabled = false;
    }
}

static void *scheduler_thread(void *arg) {
    scheduled_queue_t *sq = (scheduled_queue_t *)arg;

    while (sq->running) {
        time_t now = time(NULL);
        struct tm *tm = localtime(&now);
        int current_minute = tm->tm_min;

        pthread_mutex_lock(&sq->lock);

        for (int i = 0; i < SCHED_MAX_TASKS; i++) {
            sched_task_t *task = &sq->tasks[i];
            if (!task->in_use || !task->enabled) continue;

            // Check max runs
            if (task->max_runs > 0 && task->run_count >= task->max_runs) {
                task->enabled = false;
                continue;
            }

            bool should_run = false;

            switch (task->task_type) {
                case SCHED_TYPE_CRON:
                    // Only check once per minute
                    if (sq->last_cron_minute != current_minute) {
                        should_run = cron_matches(&task->cron_parsed, tm);
                    }
                    break;

                case SCHED_TYPE_PERIODIC:
                    if (task->last_run == 0) {
                        should_run = true;  // First run
                    } else if ((now - task->last_run) >= task->interval_seconds) {
                        should_run = true;
                    }
                    break;

                case SCHED_TYPE_ONCE:
                    if (now >= task->run_at && task->run_count == 0) {
                        should_run = true;
                    }
                    break;
            }

            if (should_run) {
                execute_task(sq, task, now);
            }
        }

        sq->last_cron_minute = current_minute;

        pthread_mutex_unlock(&sq->lock);

        // Sleep 1 second
        sleep(1);
    }

    return NULL;
}

int sched_init(scheduled_queue_t *sq, void (*send_cb)(const char*, const char*, const char*)) {
    memset(sq, 0, sizeof(*sq));
    pthread_mutex_init(&sq->lock, NULL);
    sq->send_callback = send_cb;
    sq->running = true;
    sq->last_cron_minute = -1;

    if (pthread_create(&sq->scheduler_thread, NULL, scheduler_thread, sq) != 0) {
        return -1;
    }

    return 0;
}

void sched_shutdown(scheduled_queue_t *sq) {
    sq->running = false;
    pthread_join(sq->scheduler_thread, NULL);
    pthread_mutex_destroy(&sq->lock);
}

int sched_add_cron(scheduled_queue_t *sq, const char *task_id, const char *cron_expr,
                   const char *to, const char *payload, const char *msg_type, int max_runs) {
    pthread_mutex_lock(&sq->lock);

    // Check if task_id already exists
    if (find_task(sq, task_id)) {
        pthread_mutex_unlock(&sq->lock);
        return -1;  // Duplicate
    }

    sched_task_t *task = alloc_task(sq);
    if (!task) {
        pthread_mutex_unlock(&sq->lock);
        return -2;  // Full
    }

    strncpy(task->task_id, task_id, sizeof(task->task_id) - 1);
    strncpy(task->cron_expr, cron_expr, sizeof(task->cron_expr) - 1);
    strncpy(task->to, to, sizeof(task->to) - 1);
    strncpy(task->payload, payload, sizeof(task->payload) - 1);
    strncpy(task->message_type, msg_type ? msg_type : "request", sizeof(task->message_type) - 1);

    if (parse_cron(cron_expr, &task->cron_parsed) != 0) {
        task->in_use = false;
        sq->task_count--;
        pthread_mutex_unlock(&sq->lock);
        return -3;  // Invalid cron
    }

    task->task_type = SCHED_TYPE_CRON;
    task->enabled = true;
    task->created_at = time(NULL);
    task->max_runs = max_runs;

    pthread_mutex_unlock(&sq->lock);
    return 0;
}

int sched_add_periodic(scheduled_queue_t *sq, const char *task_id, int interval_seconds,
                       const char *to, const char *payload, const char *msg_type,
                       int max_runs, bool run_immediately) {
    pthread_mutex_lock(&sq->lock);

    if (find_task(sq, task_id)) {
        pthread_mutex_unlock(&sq->lock);
        return -1;
    }

    sched_task_t *task = alloc_task(sq);
    if (!task) {
        pthread_mutex_unlock(&sq->lock);
        return -2;
    }

    strncpy(task->task_id, task_id, sizeof(task->task_id) - 1);
    strncpy(task->to, to, sizeof(task->to) - 1);
    strncpy(task->payload, payload, sizeof(task->payload) - 1);
    strncpy(task->message_type, msg_type ? msg_type : "request", sizeof(task->message_type) - 1);

    task->task_type = SCHED_TYPE_PERIODIC;
    task->interval_seconds = interval_seconds;
    task->last_run = run_immediately ? 0 : time(NULL);
    task->enabled = true;
    task->created_at = time(NULL);
    task->max_runs = max_runs;

    pthread_mutex_unlock(&sq->lock);
    return 0;
}

int sched_add_once(scheduled_queue_t *sq, const char *task_id, time_t run_at,
                   const char *to, const char *payload, const char *msg_type) {
    pthread_mutex_lock(&sq->lock);

    if (find_task(sq, task_id)) {
        pthread_mutex_unlock(&sq->lock);
        return -1;
    }

    sched_task_t *task = alloc_task(sq);
    if (!task) {
        pthread_mutex_unlock(&sq->lock);
        return -2;
    }

    strncpy(task->task_id, task_id, sizeof(task->task_id) - 1);
    strncpy(task->to, to, sizeof(task->to) - 1);
    strncpy(task->payload, payload, sizeof(task->payload) - 1);
    strncpy(task->message_type, msg_type ? msg_type : "request", sizeof(task->message_type) - 1);

    task->task_type = SCHED_TYPE_ONCE;
    task->run_at = run_at;
    task->enabled = true;
    task->created_at = time(NULL);
    task->max_runs = 1;

    pthread_mutex_unlock(&sq->lock);
    return 0;
}

int sched_remove(scheduled_queue_t *sq, const char *task_id) {
    pthread_mutex_lock(&sq->lock);

    sched_task_t *task = find_task(sq, task_id);
    if (!task) {
        pthread_mutex_unlock(&sq->lock);
        return -1;
    }

    task->in_use = false;
    sq->task_count--;

    pthread_mutex_unlock(&sq->lock);
    return 0;
}

int sched_enable(scheduled_queue_t *sq, const char *task_id, bool enabled) {
    pthread_mutex_lock(&sq->lock);

    sched_task_t *task = find_task(sq, task_id);
    if (!task) {
        pthread_mutex_unlock(&sq->lock);
        return -1;
    }

    task->enabled = enabled;

    pthread_mutex_unlock(&sq->lock);
    return 0;
}

char *sched_list_tasks(scheduled_queue_t *sq) {
    pthread_mutex_lock(&sq->lock);

    // Estimate buffer size
    size_t buf_size = 256 + sq->task_count * 512;
    char *buf = malloc(buf_size);
    if (!buf) {
        pthread_mutex_unlock(&sq->lock);
        return NULL;
    }

    char *p = buf;
    p += sprintf(p, "[");

    bool first = true;
    for (int i = 0; i < SCHED_MAX_TASKS; i++) {
        sched_task_t *t = &sq->tasks[i];
        if (!t->in_use) continue;

        if (!first) p += sprintf(p, ",");
        first = false;

        p += sprintf(p,
            "{\"task_id\":\"%s\",\"task_type\":\"%s\",\"to\":\"%s\","
            "\"enabled\":%s,\"run_count\":%d,\"max_runs\":%d,\"last_run\":%ld",
            t->task_id,
            t->task_type == SCHED_TYPE_CRON ? "cron" :
            t->task_type == SCHED_TYPE_PERIODIC ? "periodic" : "once",
            t->to,
            t->enabled ? "true" : "false",
            t->run_count,
            t->max_runs,
            (long)t->last_run);

        if (t->task_type == SCHED_TYPE_CRON) {
            p += sprintf(p, ",\"cron_expr\":\"%s\"", t->cron_expr);
        } else if (t->task_type == SCHED_TYPE_PERIODIC) {
            p += sprintf(p, ",\"interval_seconds\":%d", t->interval_seconds);
        } else if (t->task_type == SCHED_TYPE_ONCE) {
            p += sprintf(p, ",\"run_at\":%ld", (long)t->run_at);
        }

        p += sprintf(p, "}");
    }

    p += sprintf(p, "]");

    pthread_mutex_unlock(&sq->lock);
    return buf;
}

char *sched_stats(scheduled_queue_t *sq) {
    pthread_mutex_lock(&sq->lock);

    int enabled_count = 0;
    int cron_count = 0, periodic_count = 0, once_count = 0;

    for (int i = 0; i < SCHED_MAX_TASKS; i++) {
        sched_task_t *t = &sq->tasks[i];
        if (!t->in_use) continue;

        if (t->enabled) enabled_count++;

        switch (t->task_type) {
            case SCHED_TYPE_CRON: cron_count++; break;
            case SCHED_TYPE_PERIODIC: periodic_count++; break;
            case SCHED_TYPE_ONCE: once_count++; break;
        }
    }

    pthread_mutex_unlock(&sq->lock);

    char *buf = malloc(256);
    if (!buf) return NULL;

    snprintf(buf, 256,
        "{\"total_tasks\":%d,\"enabled_tasks\":%d,"
        "\"by_type\":{\"cron\":%d,\"periodic\":%d,\"once\":%d},"
        "\"scheduler_running\":%s}",
        sq->task_count, enabled_count,
        cron_count, periodic_count, once_count,
        sq->running ? "true" : "false");

    return buf;
}
