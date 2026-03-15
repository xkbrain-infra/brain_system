/*
 * Task Store — Task CRUD + YAML-like JSON 持久化
 * 使用 jansson 做 JSON 存储（比 C 实现 YAML 解析器更简洁可靠）
 */

#include "task_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

/* ── Status transitions ── */
const unsigned int VALID_TRANSITIONS[TS_COUNT] = {
    [TS_PENDING]     = TS_BIT(TS_IN_PROGRESS) | TS_BIT(TS_CANCELLED),
    [TS_IN_PROGRESS] = TS_BIT(TS_BLOCKED) | TS_BIT(TS_COMPLETED) | TS_BIT(TS_FAILED),
    [TS_BLOCKED]     = TS_BIT(TS_IN_PROGRESS) | TS_BIT(TS_CANCELLED),
    [TS_FAILED]      = TS_BIT(TS_IN_PROGRESS) | TS_BIT(TS_CANCELLED),
    [TS_COMPLETED]   = TS_BIT(TS_ARCHIVED),
    [TS_CANCELLED]   = TS_BIT(TS_ARCHIVED),
    [TS_ARCHIVED]    = 0,
};

static const char *STATUS_NAMES[] = {
    "pending", "in_progress", "blocked", "completed",
    "failed", "cancelled", "archived"
};

const char *task_status_str(TaskStatus s) {
    if (s >= 0 && s < TS_COUNT) return STATUS_NAMES[s];
    return "unknown";
}

TaskStatus task_status_from_str(const char *s) {
    if (!s) return TS_PENDING;
    for (int i = 0; i < TS_COUNT; i++) {
        if (strcmp(s, STATUS_NAMES[i]) == 0) return (TaskStatus)i;
    }
    return TS_PENDING;
}

void now_iso(char *buf, size_t len) {
    time_t t = time(NULL);
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

json_t *task_to_json(const Task *t) {
    json_t *obj = json_object();
    json_object_set_new(obj, "task_id", json_string(t->task_id));
    json_object_set_new(obj, "title", json_string(t->title));
    json_object_set_new(obj, "owner", json_string(t->owner));
    json_object_set_new(obj, "priority", json_string(t->priority));
    json_object_set_new(obj, "status", json_string(task_status_str(t->status)));
    json_object_set_new(obj, "spec_id", json_string(t->spec_id));
    json_object_set_new(obj, "group", json_string(t->group));
    json_object_set_new(obj, "description", json_string(t->description));
    json_object_set_new(obj, "deadline", json_string(t->deadline));
    json_object_set_new(obj, "created_at", json_string(t->created_at));
    json_object_set_new(obj, "updated_at", json_string(t->updated_at));

    json_t *deps = json_array();
    for (int i = 0; i < t->depends_count; i++)
        json_array_append_new(deps, json_string(t->depends_on[i]));
    json_object_set_new(obj, "depends_on", deps);

    json_t *tags = json_array();
    for (int i = 0; i < t->tags_count; i++)
        json_array_append_new(tags, json_string(t->tags[i]));
    json_object_set_new(obj, "tags", tags);

    return obj;
}

static void task_from_json(Task *t, const char *id, json_t *obj) {
    memset(t, 0, sizeof(*t));
    t->active = true;
    snprintf(t->task_id, sizeof(t->task_id), "%s", id);

    const char *v;
    if ((v = json_string_value(json_object_get(obj, "title"))))
        snprintf(t->title, sizeof(t->title), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "owner"))))
        snprintf(t->owner, sizeof(t->owner), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "priority"))))
        snprintf(t->priority, sizeof(t->priority), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "status"))))
        t->status = task_status_from_str(v);
    if ((v = json_string_value(json_object_get(obj, "spec_id"))))
        snprintf(t->spec_id, sizeof(t->spec_id), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "group"))))
        snprintf(t->group, sizeof(t->group), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "description"))))
        snprintf(t->description, sizeof(t->description), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "deadline"))))
        snprintf(t->deadline, sizeof(t->deadline), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "created_at"))))
        snprintf(t->created_at, sizeof(t->created_at), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "updated_at"))))
        snprintf(t->updated_at, sizeof(t->updated_at), "%s", v);

    json_t *deps = json_object_get(obj, "depends_on");
    if (json_is_array(deps)) {
        int n = (int)json_array_size(deps);
        if (n > TM_MAX_DEPS) n = TM_MAX_DEPS;
        for (int i = 0; i < n; i++) {
            const char *d = json_string_value(json_array_get(deps, i));
            if (d) snprintf(t->depends_on[i], TM_MAX_ID_LEN, "%s", d);
        }
        t->depends_count = n;
    }

    json_t *tags = json_object_get(obj, "tags");
    if (json_is_array(tags)) {
        int n = (int)json_array_size(tags);
        if (n > TM_MAX_TAGS) n = TM_MAX_TAGS;
        for (int i = 0; i < n; i++) {
            const char *tg = json_string_value(json_array_get(tags, i));
            if (tg) snprintf(t->tags[i], 64, "%s", tg);
        }
        t->tags_count = n;
    }
}

/* ── Init ── */
void task_store_init(TaskStore *s, const char *data_dir) {
    memset(s, 0, sizeof(*s));
    snprintf(s->data_path, sizeof(s->data_path), "%s/tasks.json", data_dir);
    pthread_mutex_init(&s->mu, NULL);
}

/* ── Load from disk ── */
int task_store_load(TaskStore *s) {
    pthread_mutex_lock(&s->mu);
    s->count = 0;

    FILE *f = fopen(s->data_path, "r");
    if (!f) {
        pthread_mutex_unlock(&s->mu);
        return 0; /* no file = empty store, ok */
    }

    json_error_t err;
    json_t *root = json_loadf(f, 0, &err);
    fclose(f);
    if (!root) {
        pthread_mutex_unlock(&s->mu);
        return -1;
    }

    json_t *tasks = json_object_get(root, "tasks");
    if (json_is_object(tasks)) {
        const char *key;
        json_t *val;
        json_object_foreach(tasks, key, val) {
            if (s->count >= TM_MAX_TASKS) break;
            task_from_json(&s->tasks[s->count], key, val);
            s->count++;
        }
    }

    json_decref(root);
    pthread_mutex_unlock(&s->mu);
    return s->count;
}

/* ── Flush to disk (atomic: .tmp → rename) ── */
int task_store_flush(TaskStore *s) {
    json_t *tasks_obj = json_object();
    for (int i = 0; i < s->count; i++) {
        if (!s->tasks[i].active) continue;
        json_object_set_new(tasks_obj, s->tasks[i].task_id, task_to_json(&s->tasks[i]));
    }

    json_t *root = json_object();
    json_object_set_new(root, "tasks", tasks_obj);

    char tmp[520];
    snprintf(tmp, sizeof(tmp), "%s.tmp", s->data_path);

    /* ensure directory */
    char dir[512];
    snprintf(dir, sizeof(dir), "%s", s->data_path);
    char *slash = strrchr(dir, '/');
    if (slash) { *slash = '\0'; mkdir(dir, 0755); }

    int rc = json_dump_file(root, tmp, JSON_INDENT(2) | JSON_ENSURE_ASCII);
    json_decref(root);
    if (rc != 0) return -1;

    if (rename(tmp, s->data_path) != 0) return -1;
    return 0;
}

/* ── CRUD ── */
int task_store_create(TaskStore *s, const Task *t) {
    pthread_mutex_lock(&s->mu);

    /* duplicate check */
    for (int i = 0; i < s->count; i++) {
        if (s->tasks[i].active && strcmp(s->tasks[i].task_id, t->task_id) == 0) {
            pthread_mutex_unlock(&s->mu);
            return -1; /* duplicate */
        }
    }

    if (s->count >= TM_MAX_TASKS) {
        pthread_mutex_unlock(&s->mu);
        return -2; /* full */
    }

    s->tasks[s->count] = *t;
    s->tasks[s->count].active = true;
    s->tasks[s->count].status = TS_PENDING;
    now_iso(s->tasks[s->count].created_at, sizeof(s->tasks[s->count].created_at));
    now_iso(s->tasks[s->count].updated_at, sizeof(s->tasks[s->count].updated_at));
    s->count++;

    task_store_flush(s);
    pthread_mutex_unlock(&s->mu);
    return 0;
}

int task_store_update(TaskStore *s, const char *task_id, json_t *updates) {
    pthread_mutex_lock(&s->mu);

    Task *t = NULL;
    for (int i = 0; i < s->count; i++) {
        if (s->tasks[i].active && strcmp(s->tasks[i].task_id, task_id) == 0) {
            t = &s->tasks[i];
            break;
        }
    }
    if (!t) { pthread_mutex_unlock(&s->mu); return -1; }

    /* status transition */
    const char *new_status = json_string_value(json_object_get(updates, "status"));
    if (new_status) {
        TaskStatus ns = task_status_from_str(new_status);
        if (!(VALID_TRANSITIONS[t->status] & TS_BIT(ns))) {
            pthread_mutex_unlock(&s->mu);
            return -3; /* invalid transition */
        }
        t->status = ns;
    }

    const char *v;
    if ((v = json_string_value(json_object_get(updates, "title"))))
        snprintf(t->title, sizeof(t->title), "%s", v);
    if ((v = json_string_value(json_object_get(updates, "owner"))))
        snprintf(t->owner, sizeof(t->owner), "%s", v);
    if ((v = json_string_value(json_object_get(updates, "priority"))))
        snprintf(t->priority, sizeof(t->priority), "%s", v);
    if ((v = json_string_value(json_object_get(updates, "description"))))
        snprintf(t->description, sizeof(t->description), "%s", v);
    if ((v = json_string_value(json_object_get(updates, "deadline"))))
        snprintf(t->deadline, sizeof(t->deadline), "%s", v);

    now_iso(t->updated_at, sizeof(t->updated_at));
    task_store_flush(s);
    pthread_mutex_unlock(&s->mu);
    return 0;
}

Task *task_store_get(TaskStore *s, const char *task_id) {
    for (int i = 0; i < s->count; i++) {
        if (s->tasks[i].active && strcmp(s->tasks[i].task_id, task_id) == 0)
            return &s->tasks[i];
    }
    return NULL;
}

json_t *task_store_query(TaskStore *s, json_t *filters) {
    pthread_mutex_lock(&s->mu);
    json_t *arr = json_array();

    const char *by = json_string_value(json_object_get(filters, "by"));
    if (!by) by = "all";

    for (int i = 0; i < s->count; i++) {
        Task *t = &s->tasks[i];
        if (!t->active) continue;

        bool match = true;
        if (strcmp(by, "id") == 0) {
            const char *fid = json_string_value(json_object_get(filters, "task_id"));
            match = fid && strcmp(t->task_id, fid) == 0;
        } else if (strcmp(by, "spec") == 0) {
            const char *sid = json_string_value(json_object_get(filters, "spec_id"));
            match = sid && strcmp(t->spec_id, sid) == 0;
        } else if (strcmp(by, "owner") == 0) {
            const char *own = json_string_value(json_object_get(filters, "owner"));
            match = own && strcmp(t->owner, own) == 0;
        } else if (strcmp(by, "status") == 0) {
            const char *st = json_string_value(json_object_get(filters, "status"));
            match = st && strcmp(task_status_str(t->status), st) == 0;
        } else if (strcmp(by, "group") == 0) {
            const char *grp = json_string_value(json_object_get(filters, "group"));
            match = grp && strcmp(t->group, grp) == 0;
        }

        if (match) json_array_append_new(arr, task_to_json(t));
    }

    pthread_mutex_unlock(&s->mu);
    return arr;
}

int task_store_delete(TaskStore *s, const char *task_id) {
    pthread_mutex_lock(&s->mu);
    Task *t = NULL;
    for (int i = 0; i < s->count; i++) {
        if (s->tasks[i].active && strcmp(s->tasks[i].task_id, task_id) == 0) {
            t = &s->tasks[i];
            break;
        }
    }
    if (!t) { pthread_mutex_unlock(&s->mu); return -1; }

    t->status = TS_ARCHIVED;
    now_iso(t->updated_at, sizeof(t->updated_at));
    task_store_flush(s);
    pthread_mutex_unlock(&s->mu);
    return 0;
}
