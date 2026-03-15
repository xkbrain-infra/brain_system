#include "google_api.h"
#include "logger.h"

#include <curl/curl.h>
#include <stdlib.h>
#include <string.h>

static const char *API_BASE_URLS[] = {
    "https://gmail.googleapis.com/gmail/v1/users/me",
    "https://www.googleapis.com/drive/v3",
    "https://www.googleapis.com/calendar/v3",
    "https://sheets.googleapis.com/v4/spreadsheets",
    "https://docs.googleapis.com/v1",
    "https://slides.googleapis.com/v1",
    "https://tasks.googleapis.com/tasks/v1",
    "https://people.googleapis.com/v1",
    "https://cloudsearch.googleapis.com/v1"
};

struct memory_buffer {
    char *data;
    size_t size;
};

static size_t write_memory_callback(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t realsize = size * nmemb;
    struct memory_buffer *mem = (struct memory_buffer *)userp;
    char *ptr = realloc(mem->data, mem->size + realsize + 1);
    if (!ptr) return 0;
    mem->data = ptr;
    memcpy(&(mem->data[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->data[mem->size] = 0;
    return realsize;
}

int google_api_init(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
    log_info("Google API module initialized");
    return 0;
}

char *google_api_call(const char *access_token, GoogleAPI api, const char *endpoint, HTTPMethod method, const char *json_body) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;

    struct memory_buffer chunk = {0};
    chunk.data = malloc(1);
    chunk.size = 0;

    char url[512];
    snprintf(url, sizeof(url), "%s%s", API_BASE_URLS[api], endpoint);

    struct curl_slist *headers = NULL;
    char auth_header[512];
    snprintf(auth_header, sizeof(auth_header), "Authorization: Bearer %s", access_token);
    headers = curl_slist_append(headers, auth_header);
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &chunk);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    switch (method) {
        case HTTP_GET:
            curl_easy_setopt(curl, CURLOPT_HTTPGET, 1L);
            break;
        case HTTP_POST:
            curl_easy_setopt(curl, CURLOPT_POST, 1L);
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
            break;
        case HTTP_PUT:
            curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PUT");
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
            break;
        case HTTP_PATCH:
            curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PATCH");
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
            break;
        case HTTP_DELETE:
            curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
            break;
    }

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        log_error("Google API call failed: %s", curl_easy_strerror(res));
        free(chunk.data);
        return NULL;
    }

    return chunk.data;
}

void google_api_free(void) {
    curl_global_cleanup();
    log_info("Google API module freed");
}
