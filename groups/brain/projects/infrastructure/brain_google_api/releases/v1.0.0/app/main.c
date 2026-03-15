#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <pthread.h>
#include <time.h>
#include <curl/curl.h>
#include <jansson.h>
#include "logger.h"
#include "config.h"
#include "account_mgr.h"
#include "acl.h"
#include "ipc_client.h"
#include "mcp_protocol.h"
#include "google_api_tool.h"
#include "google_api.h"
#include "oauth2.h"

// Global config
static Config global_config;

// Token management
static char *cached_access_token = NULL;
static char *cached_refresh_token = NULL;
static time_t token_expires_at = 0;

static int load_token_from_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        log_warn("No token file found: %s", path);
        return -1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *content = malloc(fsize + 1);
    fread(content, 1, fsize, f);
    fclose(f);
    content[fsize] = '\0';

    json_error_t error;
    json_t *root = json_loads(content, 0, &error);
    free(content);

    if (!root) {
        log_error("Failed to parse token JSON: %s", error.text);
        return -1;
    }

    json_t *access_tok = json_object_get(root, "access_token");
    json_t *refresh_tok = json_object_get(root, "refresh_token");
    json_t *expires_in = json_object_get(root, "expires_in");

    if (access_tok && json_is_string(access_tok)) {
        cached_access_token = strdup(json_string_value(access_tok));
    }
    if (refresh_tok && json_is_string(refresh_tok)) {
        cached_refresh_token = strdup(json_string_value(refresh_tok));
    }
    if (expires_in && json_is_integer(expires_in)) {
        token_expires_at = time(NULL) + json_integer_value(expires_in) - 300; // 5 min buffer
    }

    json_decref(root);
    log_info("Token loaded from file, expires in %ld seconds", (long)(token_expires_at - time(NULL)));
    return 0;
}

static int refresh_token(void) {
    if (!cached_refresh_token) {
        log_error("No refresh token available");
        return -1;
    }

    // Load credentials for client_id/secret
    char cred_path[512];
    snprintf(cred_path, sizeof(cred_path), "%s/credentials.json", global_config.secrets_path);

    FILE *f = fopen(cred_path, "r");
    if (!f) {
        log_error("Failed to open credentials: %s", cred_path);
        return -1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *content = malloc(fsize + 1);
    fread(content, 1, fsize, f);
    fclose(f);
    content[fsize] = '\0';

    json_error_t error;
    json_t *root = json_loads(content, 0, &error);
    free(content);

    if (!root) {
        log_error("Failed to parse credentials");
        return -1;
    }

    // Get first account's credentials
    const char *client_id = NULL, *client_secret = NULL;
    json_t *first_account = json_object_iter_value(json_object_iter(root));
    if (first_account) {
        json_t *cid = json_object_get(first_account, "client_id");
        json_t *csec = json_object_get(first_account, "client_secret");
        if (cid && json_is_string(cid)) client_id = json_string_value(cid);
        if (csec && json_is_string(csec)) client_secret = json_string_value(csec);
    }
    json_decref(root);

    if (!client_id || !client_secret) {
        log_error("Missing client credentials");
        return -1;
    }

    // Call refresh endpoint
    CURL *curl = curl_easy_init();
    char post_fields[2048];
    snprintf(post_fields, sizeof(post_fields),
        "client_id=%s&client_secret=%s&refresh_token=%s&grant_type=refresh_token",
        client_id, client_secret, cached_refresh_token);

    curl_easy_setopt(curl, CURLOPT_URL, "https://oauth2.googleapis.com/token");
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, post_fields);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

    char response[4096];
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, response);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, NULL);

    CURLcode res = curl_easy_perform(curl);
    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK || http_code != 200) {
        log_error("Token refresh failed: curl=%d, http=%ld", res, http_code);
        return -1;
    }

    // Parse response
    json_t *resp = json_loads(response, 0, &error);
    if (!resp) {
        log_error("Failed to parse refresh response");
        return -1;
    }

    json_t *new_access = json_object_get(resp, "access_token");
    json_t *new_expires = json_object_get(resp, "expires_in");

    if (new_access && json_is_string(new_access)) {
        free(cached_access_token);
        cached_access_token = strdup(json_string_value(new_access));
    }
    if (new_expires && json_is_integer(new_expires)) {
        token_expires_at = time(NULL) + json_integer_value(new_expires) - 300;
    }

    json_decref(resp);

    // Save new token to file
    char token_path[512];
    snprintf(token_path, sizeof(token_path), "%s/token.json", global_config.secrets_path);
    f = fopen(token_path, "w");
    if (f) {
        fprintf(f, "{\"access_token\":\"%s\",\"refresh_token\":\"%s\",\"expires_in\":%ld}",
            cached_access_token, cached_refresh_token, (long)(token_expires_at - time(NULL) + 300));
        fclose(f);
        log_info("Token refreshed and saved");
    }

    return 0;
}

static const char *get_access_token(void) {
    if (!cached_access_token) {
        // Try to load from file
        char token_path[512];
        snprintf(token_path, sizeof(token_path), "%s/token.json", global_config.secrets_path);
        load_token_from_file(token_path);
    }

    if (!cached_access_token) {
        return NULL;
    }

    // Check if token is expired or about to expire
    if (time(NULL) >= token_expires_at) {
        log_info("Token expired, refreshing...");
        if (refresh_token() != 0) {
            log_error("Failed to refresh token");
            return NULL;
        }
    }

    return cached_access_token;
}

static int load_oauth_credentials(const char *credentials_path) {
    if (!credentials_path) {
        log_warn("No GOOGLE_CREDENTIALS_PATH provided, OAuth2 not initialized");
        return -1;
    }

    FILE *f = fopen(credentials_path, "r");
    if (!f) {
        log_error("Failed to open credentials file: %s", credentials_path);
        return -1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *content = malloc(fsize + 1);
    fread(content, 1, fsize, f);
    fclose(f);
    content[fsize] = '\0';

    json_error_t error;
    json_t *root = json_loads(content, 0, &error);
    free(content);

    if (!root) {
        log_error("Failed to parse credentials JSON: %s", error.text);
        return -1;
    }

    // Support both legacy format and multi-account format
    // Legacy: { "client_id": "...", "client_secret": "..." }
    // Multi-account: { "email1@gmail.com": { "client_id": "...", "client_secret": "..." } }

    const char *client_id = json_string_value(json_object_get(root, "client_id"));
    const char *client_secret = json_string_value(json_object_get(root, "client_secret"));

    if (client_id && client_secret) {
        // Legacy format
        oauth2_init(NULL, client_id, client_secret);
        log_info("OAuth2 credentials loaded (legacy format) from: %s", credentials_path);
    } else {
        // Multi-account format - iterate through accounts
        const char *email;
        json_t *account;
        json_object_foreach(root, email, account) {
            const char *cid = json_string_value(json_object_get(account, "client_id"));
            const char *csec = json_string_value(json_object_get(account, "client_secret"));
            if (cid && csec) {
                oauth2_init(NULL, cid, csec);
                log_info("OAuth2 credentials loaded for account: %s", email);
            }
        }
    }

    json_decref(root);
    return 0;
}

static void register_tools(void) {
    google_api_tool_set_token_provider(get_access_token);
    google_api_tool_register();
}

static void *stdio_loop(void *arg) {
    log_info("stdio_loop started, waiting for input...");
    char line[8192];
    while (1) {
        if (!fgets(line, sizeof(line), stdin)) {
            // stdin closed or EOF - wait and retry
            usleep(100000); // 100ms
            continue;
        }
        line[strcspn(line, "\n")] = 0;
        log_debug("Received: %s", line);

        MCPRequest req;
        if (mcp_protocol_parse(line, &req) == 0) {
            MCPResponse resp = {0};
            strncpy(resp.id, req.id, sizeof(resp.id) - 1);

            if (strcmp(req.method, "initialize") == 0) {
                // MCP initialize handshake
                resp.result = strdup("{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"serverInfo\":{\"name\":\"brain_google_api\",\"version\":\"0.1.0\"}}");
            } else if (strcmp(req.method, "tools/list") == 0) {
                char *tools_json = mcp_protocol_list_tools();
                resp.result = tools_json;
            } else {
                mcp_protocol_dispatch(&req, &resp);
            }

            char *out = NULL;
            mcp_protocol_build_response(&resp, &out);
            if (out) {
                printf("%s\n", out);
                fflush(stdout);
                free(out);
            }

            free(req.params);
            free(resp.result);
        }
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    // Ignore SIGPIPE to prevent crashes on socket write errors
    signal(SIGPIPE, SIG_IGN);

    config_load(&global_config);
    log_init(global_config.log_level);

    // Initialize curl
    curl_global_init(CURL_GLOBAL_DEFAULT);

    log_info("brain_google_api starting...");
    log_info("Secrets path: %s", global_config.secrets_path);
    log_info("IPC socket: %s", global_config.ipc_socket);

    // Load OAuth credentials from config
    load_oauth_credentials(global_config.credentials_path);

    // Load token from file
    char token_path[512];
    snprintf(token_path, sizeof(token_path), "%s/token.json", global_config.secrets_path);
    load_token_from_file(token_path);

    account_mgr_init(global_config.secrets_path);
    acl_init("/brain/infrastructure/service/brain_google_api/config/acl.json");
    google_api_init();
    mcp_protocol_init();
    ipc_client_init(global_config.service_name, global_config.ipc_socket);

    ipc_client_register();
    log_info("Registered as: %s", global_config.service_name);

    register_tools();
    log_info("MCP tools registered");

    ipc_client_notify("SERVICE_READY");
    log_info("About to enter stdio_loop...");

    stdio_loop(NULL);

    log_info("Shutting down...");
    ipc_client_free();
    mcp_protocol_free();
    google_api_free();
    acl_free();
    account_mgr_free();

    return 0;
}
