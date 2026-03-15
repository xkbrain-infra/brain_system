#include "oauth2.h"
#include "logger.h"
#include <string.h>
#include <stdlib.h>
#include <curl/curl.h>
#include <jansson.h>

static OAuth2Config global_config = {0};

static size_t write_callback(void *ptr, size_t size, size_t nmemb, void *stream) {
    size_t realsize = size * nmemb;
    char **strp = (char **)stream;
    char *tmp = realloc(*strp, strlen(*strp) + realsize + 1);
    if (tmp) {
        *strp = tmp;
        memcpy(*strp + strlen(*strp), ptr, realsize);
        (*strp)[strlen(*strp) + realsize] = '\0';
    }
    return realsize;
}

int oauth2_init(OAuth2Config *cfg, const char *client_id, const char *client_secret) {
    strncpy(global_config.client_id, client_id, sizeof(global_config.client_id) - 1);
    strncpy(global_config.client_secret, client_secret, sizeof(global_config.client_secret) - 1);
    strncpy(global_config.redirect_uri, "http://localhost:8080/callback", sizeof(global_config.redirect_uri) - 1);

    global_config.auth_url = strdup("https://accounts.google.com/o/oauth2/v2/auth");
    global_config.token_url = strdup("https://oauth2.googleapis.com/token");

    log_info("OAuth2 initialized with client_id: %s", client_id);
    return 0;
}

char *oauth2_get_auth_url(const char *account_id) {
    char *url = malloc(1024);
    snprintf(url, 1024,
        "%s?"
        "client_id=%s&"
        "redirect_uri=%s&"
        "response_type=code&"
        "scope=email%%20profile%%20https://www.googleapis.com/auth/gmail.readonly%%20https://www.googleapis.com/auth/gmail.send%%20https://www.googleapis.com/auth/drive.file%%20https://www.googleapis.com/auth/calendar%%20https://www.googleapis.com/auth/spreadsheets%%20https://www.googleapis.com/auth/documents%%20https://www.googleapis.com/auth/presentations%%20https://www.googleapis.com/auth/tasks%%20https://www.googleapis.com/auth/contacts&"
        "state=%s&"
        "access_type=offline&"
        "prompt=consent",
        global_config.auth_url,
        global_config.client_id,
        global_config.redirect_uri,
        account_id);

    log_debug("Generated auth URL for account: %s", account_id);
    return url;
}

int oauth2_exchange_code(const char *code, OAuth2Token *token) {
    CURL *curl = curl_easy_init();
    if (!curl) return -1;

    char *response = calloc(1, 1);
    char postfields[2048];
    snprintf(postfields, sizeof(postfields),
        "code=%s&"
        "client_id=%s&"
        "client_secret=%s&"
        "redirect_uri=%s&"
        "grant_type=authorization_code",
        code,
        global_config.client_id,
        global_config.client_secret,
        global_config.redirect_uri);

    curl_easy_setopt(curl, CURLOPT_URL, global_config.token_url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, postfields);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        log_error("OAuth2 token exchange failed: %s", curl_easy_strerror(res));
        free(response);
        return -1;
    }

    json_error_t error;
    json_t *root = json_loads(response, 0, &error);
    free(response);

    if (!root) {
        log_error("Failed to parse token response: %s", error.text);
        return -1;
    }

    json_t *access_token_json = json_object_get(root, "access_token");
    json_t *refresh_token_json = json_object_get(root, "refresh_token");
    json_t *expires_in_json = json_object_get(root, "expires_in");

    if (access_token_json) {
        token->access_token = strdup(json_string_value(access_token_json));
    }
    if (refresh_token_json) {
        token->refresh_token = strdup(json_string_value(refresh_token_json));
    }
    if (expires_in_json) {
        token->expires_in = json_integer_value(expires_in_json);
    }
    token->token_obtained = time(NULL);

    json_decref(root);
    log_info("OAuth2 token obtained successfully");
    return 0;
}

int oauth2_refresh(const char *refresh_token, OAuth2Token *token) {
    CURL *curl = curl_easy_init();
    if (!curl) return -1;

    char *response = calloc(1, 1);
    char postfields[2048];
    snprintf(postfields, sizeof(postfields),
        "refresh_token=%s&"
        "client_id=%s&"
        "client_secret=%s&"
        "grant_type=refresh_token",
        refresh_token,
        global_config.client_id,
        global_config.client_secret);

    curl_easy_setopt(curl, CURLOPT_URL, global_config.token_url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, postfields);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        log_error("OAuth2 token refresh failed: %s", curl_easy_strerror(res));
        free(response);
        return -1;
    }

    json_error_t error;
    json_t *root = json_loads(response, 0, &error);
    free(response);

    if (!root) {
        log_error("Failed to parse refresh response: %s", error.text);
        return -1;
    }

    json_t *access_token_json = json_object_get(root, "access_token");
    json_t *expires_in_json = json_object_get(root, "expires_in");

    if (access_token_json) {
        if (token->access_token) free(token->access_token);
        token->access_token = strdup(json_string_value(access_token_json));
    }
    if (expires_in_json) {
        token->expires_in = json_integer_value(expires_in_json);
    } else {
        token->expires_in = 3600;
    }
    token->token_obtained = time(NULL);

    json_decref(root);
    log_info("OAuth2 token refreshed successfully");
    return 0;
}

void oauth2_token_free(OAuth2Token *token) {
    if (token) {
        free(token->access_token);
        free(token->refresh_token);
        memset(token, 0, sizeof(OAuth2Token));
    }
}

void oauth2_free(void) {
    free(global_config.auth_url);
    free(global_config.token_url);
    memset(&global_config, 0, sizeof(OAuth2Config));
    log_info("OAuth2 cleanup complete");
}
