#ifndef CONFIG_H
#define CONFIG_H

#include <stdbool.h>

typedef struct {
    char secrets_path[256];
    char log_level[16];
    char ipc_socket[256];
    char service_name[64];
    char credentials_path[256];
} Config;

int config_load(Config *cfg);
int config_save_acl(const char *path, const char *json);
int config_load_acl(const char *path, char **out_json);
int config_save_resources(const char *path, const char *json);
int config_load_resources(const char *path, char **out_json);

#endif
