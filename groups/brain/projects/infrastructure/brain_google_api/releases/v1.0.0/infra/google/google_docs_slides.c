#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>

int google_api_docs_create_document(const char *access_token, const char *title, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "title", json_string(title ? title : "Untitled"));

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_DOCS, "/documents", HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_docs_get_document(const char *access_token, const char *document_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/documents/%s", document_id);

    char *result = google_api_call(access_token, API_DOCS, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_docs_update_document(const char *access_token, const char *document_id, const char *requests_json, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/documents/%s:batchUpdate", document_id);

    char *result = google_api_call(access_token, API_DOCS, endpoint, HTTP_POST, requests_json);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_slides_create_presentation(const char *access_token, const char *title, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "title", json_string(title ? title : "Untitled Presentation"));

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_SLIDES, "/presentations", HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_slides_get_presentation(const char *access_token, const char *presentation_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/presentations/%s", presentation_id);

    char *result = google_api_call(access_token, API_SLIDES, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_slides_add_slide(const char *access_token, const char *presentation_id, int slide_index, char **response) {
    (void)slide_index;

    json_t *root = json_object();
    json_t *requests = json_array();

    json_t *request = json_object();
    json_object_set_new(request, "createSlide", json_object());
    json_array_append_new(requests, request);
    json_object_set_new(root, "requests", requests);

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/presentations/%s:batchUpdate", presentation_id);

    char *result = google_api_call(access_token, API_SLIDES, endpoint, HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}
