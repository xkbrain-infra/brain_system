#include "google_api.h"

#include <jansson.h>
#include <base64.h>
#include <stdlib.h>
#include <string.h>

int google_api_gmail_list_messages(const char *access_token, const char *query, int max_results, char **response) {
    char endpoint[256];
    if (query && strlen(query) > 0) {
        snprintf(endpoint, sizeof(endpoint), "/messages?maxResults=%d&q=%s", max_results, query);
    } else {
        snprintf(endpoint, sizeof(endpoint), "/messages?maxResults=%d", max_results);
    }

    char *result = google_api_call(access_token, API_GMAIL, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_gmail_send_message(const char *access_token, const char *to, const char *subject, const char *body, char **response) {
    char email[8192];
    snprintf(email, sizeof(email),
        "To: %s\r\n"
        "Subject: %s\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n"
        "\r\n"
        "%s\r\n",
        to, subject, body);

    char *b64 = base64_encode((const unsigned char *)email, strlen(email));
    if (!b64) return -1;

    for (char *p = b64; *p; p++) {
        if (*p == '+') *p = '-';
        else if (*p == '/') *p = '_';
        else if (*p == '=') *p = '\0';
    }

    json_t *root = json_object();
    json_object_set_new(root, "raw", json_string(b64));
    char *json_str = json_dumps(root, 0);
    json_decref(root);
    free(b64);

    char *result = google_api_call(access_token, API_GMAIL, "/messages/send", HTTP_POST, json_str);
    free(json_str);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_gmail_get_message(const char *access_token, const char *message_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/messages/%s", message_id);

    char *result = google_api_call(access_token, API_GMAIL, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_gmail_modify_message(const char *access_token, const char *message_id, const char *labels_add, const char *labels_remove, char **response) {
    json_t *root = json_object();

    if (labels_add) {
        json_t *add_labels = json_array();
        json_array_append_new(add_labels, json_string(labels_add));
        json_object_set_new(root, "addLabelIds", add_labels);
    }
    if (labels_remove) {
        json_t *remove_labels = json_array();
        json_array_append_new(remove_labels, json_string(labels_remove));
        json_object_set_new(root, "removeLabelIds", remove_labels);
    }

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/messages/%s/modify", message_id);

    char *result = google_api_call(access_token, API_GMAIL, endpoint, HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_gmail_search(const char *access_token, const char *query, int max_results, char **response) {
    return google_api_gmail_list_messages(access_token, query, max_results, response);
}

int google_api_gmail_create_label(const char *access_token, const char *name, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "name", json_string(name));
    json_object_set_new(root, "labelListVisibility", json_string("labelShow"));
    json_object_set_new(root, "messageListVisibility", json_string("show"));

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char *result = google_api_call(access_token, API_GMAIL, "/labels", HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}
