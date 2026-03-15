/*
 * Task Validator — 入站消息校验
 * validate_task_create / validate_task_update
 */

#include "task_manager.h"
#include <stdio.h>
#include <string.h>

static const char *ALLOWED_PRIORITIES[] = {
    "critical", "high", "normal", "low", NULL
};

static bool is_valid_priority(const char *p) {
    if (!p) return false;
    for (int i = 0; ALLOWED_PRIORITIES[i]; i++)
        if (strcmp(p, ALLOWED_PRIORITIES[i]) == 0) return true;
    return false;
}

/*
 * validate_task_create — 校验 TASK_CREATE payload
 *
 * 返回: NULL = 通过, 否则返回 JSON array of error strings
 * 检查项:
 *   1. required_fields: task_id, title, owner, priority
 *   2. format_check: priority in {critical,high,normal,low}, task_id 非空
 *   3. duplicate_check: store 中不存在同 task_id
 */
json_t *validate_task_create(json_t *payload, TaskStore *store) {
    json_t *errors = json_array();

    if (!payload || !json_is_object(payload)) {
        json_array_append_new(errors, json_string("payload must be a JSON object"));
        return errors;
    }

    /* 1. required fields */
    static const char *required[] = { "task_id", "title", "owner", "priority", NULL };
    for (int i = 0; required[i]; i++) {
        const char *v = json_string_value(json_object_get(payload, required[i]));
        if (!v || v[0] == '\0') {
            char buf[128];
            snprintf(buf, sizeof(buf), "missing or empty required field: %s", required[i]);
            json_array_append_new(errors, json_string(buf));
        }
    }

    /* early return if required fields missing */
    if (json_array_size(errors) > 0) return errors;

    const char *task_id  = json_string_value(json_object_get(payload, "task_id"));
    const char *priority = json_string_value(json_object_get(payload, "priority"));

    /* 2. format check */
    if (!is_valid_priority(priority)) {
        char buf[128];
        snprintf(buf, sizeof(buf),
                 "invalid priority '%s', must be one of: critical, high, normal, low", priority);
        json_array_append_new(errors, json_string(buf));
    }

    /* 3. duplicate check */
    if (store) {
        Task *existing = task_store_get(store, task_id);
        if (existing) {
            char buf[256];
            snprintf(buf, sizeof(buf), "duplicate task_id: %s already exists", task_id);
            json_array_append_new(errors, json_string(buf));
        }
    }

    if (json_array_size(errors) == 0) {
        json_decref(errors);
        return NULL; /* pass */
    }
    return errors;
}

/*
 * validate_task_update — 校验 TASK_UPDATE payload
 *
 * 返回: NULL = 通过, 否则返回 JSON array of error strings
 * 检查项:
 *   1. task_id 必须存在
 *   2. task 必须在 store 中存在
 *   3. status 转换必须合法
 *   4. priority 若提供必须合法
 */
json_t *validate_task_update(json_t *payload, TaskStore *store) {
    json_t *errors = json_array();

    if (!payload || !json_is_object(payload)) {
        json_array_append_new(errors, json_string("payload must be a JSON object"));
        return errors;
    }

    const char *task_id = json_string_value(json_object_get(payload, "task_id"));
    if (!task_id || task_id[0] == '\0') {
        json_array_append_new(errors, json_string("missing or empty required field: task_id"));
        return errors;
    }

    /* task must exist */
    if (!store) {
        json_array_append_new(errors, json_string("internal error: store is NULL"));
        return errors;
    }

    Task *t = task_store_get(store, task_id);
    if (!t) {
        char buf[256];
        snprintf(buf, sizeof(buf), "task not found: %s", task_id);
        json_array_append_new(errors, json_string(buf));
        return errors;
    }

    /* status transition check */
    const char *new_status = json_string_value(json_object_get(payload, "status"));
    if (new_status) {
        TaskStatus ns = task_status_from_str(new_status);
        if (strcmp(new_status, task_status_str(ns)) != 0) {
            char buf[128];
            snprintf(buf, sizeof(buf), "unknown status: %s", new_status);
            json_array_append_new(errors, json_string(buf));
        } else if (!(VALID_TRANSITIONS[t->status] & TS_BIT(ns))) {
            char buf[256];
            snprintf(buf, sizeof(buf), "invalid transition: %s -> %s",
                     task_status_str(t->status), new_status);
            json_array_append_new(errors, json_string(buf));
        }
    }

    /* priority format check (if provided) */
    const char *new_priority = json_string_value(json_object_get(payload, "priority"));
    if (new_priority && !is_valid_priority(new_priority)) {
        char buf[128];
        snprintf(buf, sizeof(buf),
                 "invalid priority '%s', must be one of: critical, high, normal, low", new_priority);
        json_array_append_new(errors, json_string(buf));
    }

    if (json_array_size(errors) == 0) {
        json_decref(errors);
        return NULL;
    }
    return errors;
}
