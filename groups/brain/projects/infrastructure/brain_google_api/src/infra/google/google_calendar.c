#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>
#include <string.h>

int google_api_calendar_list_events(const char *access_token, const char *calendar_id, const char *time_min, const char *time_max, char **response) {
    char endpoint[512] = "/calendars/";
    strcat(endpoint, calendar_id ? calendar_id : "primary");
    strcat(endpoint, "/events");

    char params[256] = "";
    if (time_min) {
        strcat(params, "timeMin=");
        strcat(params, time_min);
        strcat(params, "&");
    }
    if (time_max) {
        strcat(params, "timeMax=");
        strcat(params, time_max);
    }

    if (strlen(params) > 0) {
        strcat(endpoint, "?");
        strcat(endpoint, params);
    }

    char *result = google_api_call(access_token, API_CALENDAR, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_calendar_create_event(const char *access_token, const char *calendar_id, const char *summary, const char *description, const char *start_time, const char *end_time, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "summary", json_string(summary));
    if (description) {
        json_object_set_new(root, "description", json_string(description));
    }

    json_t *start_obj = json_object();
    json_object_set_new(start_obj, "dateTime", json_string(start_time));
    json_object_set_new(root, "start", start_obj);

    json_t *end_obj = json_object();
    json_object_set_new(end_obj, "dateTime", json_string(end_time));
    json_object_set_new(root, "end", end_obj);

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/calendars/%s/events", calendar_id ? calendar_id : "primary");

    char *result = google_api_call(access_token, API_CALENDAR, endpoint, HTTP_POST, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_calendar_update_event(const char *access_token, const char *calendar_id, const char *event_id, const char *summary, const char *description, const char *start_time, const char *end_time, char **response) {
    json_t *root = json_object();

    if (summary) json_object_set_new(root, "summary", json_string(summary));
    if (description) json_object_set_new(root, "description", json_string(description));

    if (start_time) {
        json_t *start_obj = json_object();
        json_object_set_new(start_obj, "dateTime", json_string(start_time));
        json_object_set_new(root, "start", start_obj);
    }

    if (end_time) {
        json_t *end_obj = json_object();
        json_object_set_new(end_obj, "dateTime", json_string(end_time));
        json_object_set_new(root, "end", end_obj);
    }

    char *json_body = json_dumps(root, 0);
    json_decref(root);

    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/calendars/%s/events/%s", calendar_id ? calendar_id : "primary", event_id);

    char *result = google_api_call(access_token, API_CALENDAR, endpoint, HTTP_PATCH, json_body);
    free(json_body);
    if (!result) return -1;

    *response = result;
    return 0;
}

int google_api_calendar_delete_event(const char *access_token, const char *calendar_id, const char *event_id) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/calendars/%s/events/%s", calendar_id ? calendar_id : "primary", event_id);

    char *result = google_api_call(access_token, API_CALENDAR, endpoint, HTTP_DELETE, NULL);
    free(result);
    return result ? 0 : -1;
}
