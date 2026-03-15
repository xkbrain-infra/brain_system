#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>

int google_api_people_list_connections(const char *access_token, int page_size, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/people/me/connections?pageSize=%d&personFields=names,emailAddresses,phoneNumbers", page_size);
    char *result = google_api_call(access_token, API_PEOPLE, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_people_get_profile(const char *access_token, char **response) {
    char *result = google_api_call(access_token, API_PEOPLE, "/people/me?personFields=names,emailAddresses,phoneNumbers,photos", HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_people_create_contact(const char *access_token, const char *given_name, const char *family_name, const char *email, char **response) {
    json_t *root = json_object();
    json_t *names = json_array();
    json_t *name = json_object();
    json_object_set_new(name, "givenName", json_string(given_name));
    json_object_set_new(name, "familyName", json_string(family_name));
    json_array_append_new(names, name);
    json_object_set_new(root, "names", names);

    if (email) {
        json_t *emails = json_array();
        json_t *email_obj = json_object();
        json_object_set_new(email_obj, "value", json_string(email));
        json_array_append_new(emails, email_obj);
        json_object_set_new(root, "emailAddresses", emails);
    }

    char *json_str = json_dumps(root, 0);
    json_decref(root);
    char *result = google_api_call(access_token, API_PEOPLE, "/people:createContact", HTTP_POST, json_str);
    free(json_str);

    *response = result;
    return result ? 0 : -1;
}
