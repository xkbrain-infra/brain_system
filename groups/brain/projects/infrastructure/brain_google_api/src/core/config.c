#include "config.h"
#include "logger.h"
#include <string.h>
#include <jansson.h>

static Config global_config = {
    .secrets_path = "/brain/secrets/brain_google_api",
    .log_level = "info",
    .ipc_socket = "/tmp/brain_ipc.sock",
    .service_name = "service-brain_google_api",
    .credentials_path = "/brain/secrets/brain_google_api/credentials.json"
};

int config_load(Config *cfg) {
    memcpy(cfg, &global_config, sizeof(Config));
    log_info("Config loaded: secrets=%s", cfg->secrets_path);
    return 0;
}

int config_save_acl(const char *path, const char *json) {
    FILE *f = fopen(path, "w");
    if (!f) {
        log_error("Failed to open ACL config: %s", path);
        return -1;
    }
    fprintf(f, "%s", json);
    fclose(f);
    log_info("ACL config saved: %s", path);
    return 0;
}

int config_load_acl(const char *path, char **out_json) {
    FILE *f = fopen(path, "r");
    if (!f) {
        log_error("Failed to open ACL config: %s", path);
        return -1;
    }
    
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    
    *out_json = malloc(len + 1);
    fread(*out_json, 1, len, f);
    (*out_json)[len] = '\0';
    fclose(f);
    
    return 0;
}

int config_save_resources(const char *path, const char *json) {
    FILE *f = fopen(path, "w");
    if (!f) {
        log_error("Failed to open resources config: %s", path);
        return -1;
    }
    fprintf(f, "%s", json);
    fclose(f);
    log_info("Resources config saved: %s", path);
    return 0;
}

int config_load_resources(const char *path, char **out_json) {
    FILE *f = fopen(path, "r");
    if (!f) {
        log_error("Failed to open resources config: %s", path);
        return -1;
    }
    
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    
    *out_json = malloc(len + 1);
    fread(*out_json, 1, len, f);
    (*out_json)[len] = '\0';
    fclose(f);
    
    return 0;
}
