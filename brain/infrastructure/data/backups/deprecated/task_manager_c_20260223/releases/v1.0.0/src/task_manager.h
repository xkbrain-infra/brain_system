/*
 * Service Task Manager - Header
 * Spec/Task 生命周期管理服务 (C implementation)
 *
 * IPC name: service-task_manager
 * Protocol: JSON over Unix Socket (same as brain_ipc)
 */

#ifndef TASK_MANAGER_H
#define TASK_MANAGER_H

#include <jansson.h>
#include <stdbool.h>
#include <time.h>
#include <pthread.h>

/* ── Limits ── */
#define TM_MAX_TASKS        2048
#define TM_MAX_SPECS        256
#define TM_MAX_ID_LEN       128
#define TM_MAX_TITLE_LEN    256
#define TM_MAX_OWNER_LEN    128
#define TM_MAX_STR_LEN      512
#define TM_MAX_TAGS         16
#define TM_MAX_DEPS         16
#define TM_BUFFER_SIZE      65536

/* ── Task Status ── */
typedef enum {
    TS_PENDING = 0,
    TS_IN_PROGRESS,
    TS_BLOCKED,
    TS_COMPLETED,
    TS_FAILED,
    TS_CANCELLED,
    TS_ARCHIVED,
    TS_COUNT
} TaskStatus;

/* ── Status transitions ── */
/* valid_transitions[current] is bitmask of allowed target statuses */
extern const unsigned int VALID_TRANSITIONS[TS_COUNT];
#define TS_BIT(s) (1u << (s))

/* ── Spec Stage ── */
typedef enum {
    SS_S1_ALIGNMENT = 1,
    SS_S2_REQUIREMENTS,
    SS_S3_RESEARCH,
    SS_S4_ANALYSIS,
    SS_S5_SOLUTION,
    SS_S6_TASKS,
    SS_S7_VERIFICATION,
    SS_S8_COMPLETE,
    SS_ARCHIVED
} SpecStage;

/* ── Task ── */
typedef struct {
    char task_id[TM_MAX_ID_LEN];
    char title[TM_MAX_TITLE_LEN];
    char owner[TM_MAX_OWNER_LEN];
    char priority[16];            /* critical/high/normal/low */
    TaskStatus status;
    char spec_id[TM_MAX_ID_LEN];
    char group[TM_MAX_ID_LEN];
    char description[TM_MAX_STR_LEN];
    char depends_on[TM_MAX_DEPS][TM_MAX_ID_LEN];
    int  depends_count;
    char deadline[32];            /* ISO8601 */
    char tags[TM_MAX_TAGS][64];
    int  tags_count;
    char created_at[32];
    char updated_at[32];
    bool active;                  /* false = slot unused */
} Task;

/* ── Spec Record ── */
typedef struct {
    char spec_id[TM_MAX_ID_LEN];
    char title[TM_MAX_TITLE_LEN];
    char group[TM_MAX_ID_LEN];
    char owner[TM_MAX_OWNER_LEN];
    SpecStage stage;
    char created_at[32];
    char updated_at[32];
    bool active;
} SpecRecord;

/* ── Task Store ── */
typedef struct {
    Task tasks[TM_MAX_TASKS];
    int count;
    char data_path[512];
    pthread_mutex_t mu;
} TaskStore;

void  task_store_init(TaskStore *s, const char *data_dir);
int   task_store_load(TaskStore *s);
int   task_store_flush(TaskStore *s);
int   task_store_create(TaskStore *s, const Task *t);
int   task_store_update(TaskStore *s, const char *task_id, json_t *updates);
Task *task_store_get(TaskStore *s, const char *task_id);
json_t *task_store_query(TaskStore *s, json_t *filters);
int   task_store_delete(TaskStore *s, const char *task_id);

/* ── Spec Manager ── */
typedef struct {
    SpecRecord specs[TM_MAX_SPECS];
    int count;
    char data_path[512];
    pthread_mutex_t mu;
} SpecStore;

void  spec_store_init(SpecStore *s, const char *data_dir);
int   spec_store_load(SpecStore *s);
int   spec_store_flush(SpecStore *s);
int   spec_store_create(SpecStore *s, const char *spec_id, const char *title,
                         const char *group, const char *owner);
int   spec_store_advance(SpecStore *s, const char *spec_id, const char *target_stage, bool force);
json_t *spec_store_query(SpecStore *s, json_t *filters);
SpecRecord *spec_store_get(SpecStore *s, const char *spec_id);

/* ── Validator ── */
json_t *validate_task_create(json_t *payload, TaskStore *store);
json_t *validate_task_update(json_t *payload, TaskStore *store);

/* ── Utilities ── */
const char *task_status_str(TaskStatus s);
TaskStatus  task_status_from_str(const char *s);
const char *spec_stage_str(SpecStage s);
SpecStage   spec_stage_from_str(const char *s);
void        now_iso(char *buf, size_t len);
json_t     *task_to_json(const Task *t);

#endif /* TASK_MANAGER_H */
