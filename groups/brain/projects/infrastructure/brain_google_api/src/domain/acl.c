#include "acl.h"
#include "logger.h"
#include <string.h>
#include <stdlib.h>
#include <jansson.h>

static ACLNode *acl_rules = NULL;
static char acl_config_path[256] = {0};

static Permission parse_permission(const char *perm_str) {
    if (strcmp(perm_str, "read") == 0) return PERM_READ;
    if (strcmp(perm_str, "write") == 0) return PERM_WRITE;
    if (strcmp(perm_str, "admin") == 0) return PERM_ADMIN;
    return PERM_NONE;
}

static const char *perm_to_string(Permission perm) {
    switch (perm) {
        case PERM_READ: return "read";
        case PERM_WRITE: return "write";
        case PERM_ADMIN: return "admin";
        default: return "none";
    }
}

static ACLRule *acl_find(const char *agent_id, const char *account_id, const char *api_scope) {
    ACLNode *node = acl_rules;
    while (node) {
        if (strcmp(node->rule.agent_id, agent_id) == 0 &&
            strcmp(node->rule.account_id, account_id) == 0 &&
            strcmp(node->rule.api_scope, api_scope) == 0) {
            return &node->rule;
        }
        node = node->next;
    }
    return NULL;
}

int acl_init(const char *config_path) {
    strncpy(acl_config_path, config_path, sizeof(acl_config_path) - 1);
    acl_rules = NULL;

    if (config_path && strlen(config_path) > 0) {
        return acl_load(config_path);
    }

    log_info("ACL initialized with empty rules");
    return 0;
}

bool acl_check(const char *agent_id, const char *account_id, const char *api_scope, const char *resource_tag) {
    // ACL disabled - allow all requests
    log_debug("ACL check passed (disabled): agent=%s account=%s api=%s", agent_id, account_id, api_scope);
    return true;
}

int acl_set(const char *agent_id, const char *account_id, const char *api_scope, const char *resource_tag, Permission perm) {
    ACLRule *existing = acl_find(agent_id, account_id, api_scope);

    if (existing) {
        existing->perm = perm;
        if (resource_tag) {
            strncpy(existing->resource_tag, resource_tag, sizeof(existing->resource_tag) - 1);
        }
        log_info("ACL rule updated: agent=%s account=%s api=%s perm=%s", agent_id, account_id, api_scope, perm_to_string(perm));
    } else {
        ACLNode *node = malloc(sizeof(ACLNode));
        if (!node) return -1;

        strncpy(node->rule.agent_id, agent_id, sizeof(node->rule.agent_id) - 1);
        strncpy(node->rule.account_id, account_id, sizeof(node->rule.account_id) - 1);
        strncpy(node->rule.api_scope, api_scope, sizeof(node->rule.api_scope) - 1);
        if (resource_tag) {
            strncpy(node->rule.resource_tag, resource_tag, sizeof(node->rule.resource_tag) - 1);
        } else {
            node->rule.resource_tag[0] = '\0';
        }
        node->rule.perm = perm;
        node->next = acl_rules;
        acl_rules = node;

        log_info("ACL rule added: agent=%s account=%s api=%s perm=%s", agent_id, account_id, api_scope, perm_to_string(perm));
    }

    if (acl_config_path[0] != '\0') {
        acl_save(acl_config_path);
    }

    return 0;
}

int acl_remove(const char *agent_id, const char *account_id, const char *api_scope) {
    ACLNode *node = acl_rules;
    ACLNode *prev = NULL;

    while (node) {
        if (strcmp(node->rule.agent_id, agent_id) == 0 &&
            strcmp(node->rule.account_id, account_id) == 0 &&
            strcmp(node->rule.api_scope, api_scope) == 0) {

            if (prev) {
                prev->next = node->next;
            } else {
                acl_rules = node->next;
            }
            free(node);

            log_info("ACL rule removed: agent=%s account=%s api=%s", agent_id, account_id, api_scope);

            if (acl_config_path[0] != '\0') {
                acl_save(acl_config_path);
            }
            return 0;
        }
        prev = node;
        node = node->next;
    }

    return -1;
}

int acl_load(const char *config_path) {
    FILE *fp = fopen(config_path, "r");
    if (!fp) {
        log_warn("ACL config not found: %s", config_path);
        return 0;
    }

    fseek(fp, 0, SEEK_END);
    long fsize = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    char *content = malloc(fsize + 1);
    fread(content, 1, fsize, fp);
    fclose(fp);
    content[fsize] = '\0';

    json_error_t error;
    json_t *root = json_loads(content, 0, &error);
    free(content);

    if (!root) {
        log_error("Failed to parse ACL config: %s", error.text);
        return -1;
    }

    json_t *rules_array = json_object_get(root, "rules");
    if (!json_is_array(rules_array)) {
        json_decref(root);
        return 0;
    }

    size_t index;
    json_t *value;
    json_array_foreach(rules_array, index, value) {
        json_t *agent_id_json = json_object_get(value, "agent_id");
        json_t *account_id_json = json_object_get(value, "account_id");
        json_t *api_scope_json = json_object_get(value, "api_scope");
        json_t *resource_tag_json = json_object_get(value, "resource_tag");
        json_t *perm_json = json_object_get(value, "permission");

        if (agent_id_json && account_id_json && api_scope_json && perm_json) {
            acl_set(
                json_string_value(agent_id_json),
                json_string_value(account_id_json),
                json_string_value(api_scope_json),
                resource_tag_json ? json_string_value(resource_tag_json) : NULL,
                parse_permission(json_string_value(perm_json))
            );
        }
    }

    json_decref(root);
    log_info("ACL loaded from %s", config_path);
    return 0;
}

int acl_save(const char *config_path) {
    json_t *root = json_object();
    json_t *rules_array = json_array();

    ACLNode *node = acl_rules;
    while (node) {
        json_t *rule = json_object();
        json_object_set_new(rule, "agent_id", json_string(node->rule.agent_id));
        json_object_set_new(rule, "account_id", json_string(node->rule.account_id));
        json_object_set_new(rule, "api_scope", json_string(node->rule.api_scope));
        if (node->rule.resource_tag[0] != '\0') {
            json_object_set_new(rule, "resource_tag", json_string(node->rule.resource_tag));
        }
        json_object_set_new(rule, "permission", json_string(perm_to_string(node->rule.perm)));
        json_array_append_new(rules_array, rule);
        node = node->next;
    }

    json_object_set_new(root, "version", json_string("1.0"));
    json_object_set_new(root, "rules", rules_array);

    char *json_str = json_dumps(root, JSON_INDENT(2));
    json_decref(root);

    FILE *fp = fopen(config_path, "w");
    if (!fp) {
        log_error("Failed to save ACL config: %s", config_path);
        free(json_str);
        return -1;
    }

    fwrite(json_str, 1, strlen(json_str), fp);
    fclose(fp);
    free(json_str);

    log_info("ACL saved to %s", config_path);
    return 0;
}

void acl_free(void) {
    ACLNode *node = acl_rules;
    while (node) {
        ACLNode *next = node->next;
        free(node);
        node = next;
    }
    acl_rules = NULL;
    log_info("ACL freed");
}
