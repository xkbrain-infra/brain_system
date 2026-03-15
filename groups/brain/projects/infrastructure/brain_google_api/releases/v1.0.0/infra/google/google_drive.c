#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>
#include <string.h>

int google_api_drive_list_files(const char *access_token, const char *folder_id, char **response) {
    char endpoint[256];
    if (folder_id && strlen(folder_id) > 0) {
        snprintf(endpoint, sizeof(endpoint), "/files?q='%s'+in+parents", folder_id);
    } else {
        snprintf(endpoint, sizeof(endpoint), "/files");
    }

    char *result = google_api_call(access_token, API_DRIVE, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_drive_upload_file(const char *access_token, const char *parent_id, const char *name, const char *content_type, const char *content, char **response) {
    (void)content_type;
    (void)content;
    json_t *root = json_object();
    json_object_set_new(root, "name", json_string(name));
    if (parent_id) {
        json_t *parents = json_array();
        json_array_append_new(parents, json_string(parent_id));
        json_object_set_new(root, "parents", parents);
    }

    char *metadata = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_DRIVE, "/files", HTTP_POST, metadata);
    free(metadata);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_drive_download_file(const char *access_token, const char *file_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/files/%s?alt=media", file_id);

    char *result = google_api_call(access_token, API_DRIVE, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_drive_create_folder(const char *access_token, const char *parent_id, const char *name, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "name", json_string(name));
    json_object_set_new(root, "mimeType", json_string("application/vnd.google-apps.folder"));

    if (parent_id) {
        json_t *parents = json_array();
        json_array_append_new(parents, json_string(parent_id));
        json_object_set_new(root, "parents", parents);
    }

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_DRIVE, "/files", HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_drive_delete_file(const char *access_token, const char *file_id) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/files/%s", file_id);

    char *result = google_api_call(access_token, API_DRIVE, endpoint, HTTP_DELETE, NULL);
    free(result);
    return result ? 0 : -1;
}

int google_api_drive_move_file(const char *access_token, const char *file_id, const char *new_parent_id, char **response) {
    json_t *root = json_object();
    json_t *parents = json_array();
    json_array_append_new(parents, json_string(new_parent_id));
    json_object_set_new(root, "parents", parents);

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/files/%s", file_id);

    char *result = google_api_call(access_token, API_DRIVE, endpoint, HTTP_PATCH, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}
