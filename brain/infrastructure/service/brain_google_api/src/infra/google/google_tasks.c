#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>

int google_api_tasks_list_tasklists(const char *access_token, char **response) {
    char *result = google_api_call(access_token, API_TASKS, "/lists", HTTP_GET, NULL);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_tasks_create_tasklist(const char *access_token, const char *title, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "title", json_string(title ? title : "New Task List"));

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_TASKS, "/lists", HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_tasks_list_tasks(const char *access_token, const char *tasklist_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/lists/%s/tasks", tasklist_id ? tasklist_id : "@default");

    char *result = google_api_call(access_token, API_TASKS, endpoint, HTTP_GET, NULL);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_tasks_create_task(const char *access_token, const char *tasklist_id, const char *title, const char *due_date, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "title", json_string(title ? title : "New Task"));
    if (due_date) {
        json_object_set_new(root, "due", json_string(due_date));
    }

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/lists/%s/tasks", tasklist_id ? tasklist_id : "@default");

    char *result = google_api_call(access_token, API_TASKS, endpoint, HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_tasks_update_task(const char *access_token, const char *tasklist_id, const char *task_id, const char *title, const char *due_date, char **response) {
    json_t *root = json_object();
    if (title) json_object_set_new(root, "title", json_string(title));
    if (due_date) json_object_set_new(root, "due", json_string(due_date));

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/lists/%s/tasks/%s", tasklist_id ? tasklist_id : "@default", task_id);

    char *result = google_api_call(access_token, API_TASKS, endpoint, HTTP_PUT, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_tasks_delete_task(const char *access_token, const char *tasklist_id, const char *task_id) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/lists/%s/tasks/%s", tasklist_id ? tasklist_id : "@default", task_id);

    char *result = google_api_call(access_token, API_TASKS, endpoint, HTTP_DELETE, NULL);
    free(result);

    return result ? 0 : -1;
}
