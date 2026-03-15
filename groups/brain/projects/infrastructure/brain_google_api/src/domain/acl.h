#ifndef ACL_H
#define ACL_H

#include <stdbool.h>

typedef enum {
    PERM_NONE = 0,
    PERM_READ = 1,
    PERM_WRITE = 2,
    PERM_ADMIN = 3
} Permission;

typedef struct {
    char agent_id[64];
    char account_id[64];
    char api_scope[32];
    char resource_tag[64];
    Permission perm;
} ACLRule;

typedef struct ACLNode {
    ACLRule rule;
    struct ACLNode *next;
} ACLNode;

int acl_init(const char *config_path);
bool acl_check(const char *agent_id, const char *account_id, const char *api_scope, const char *resource_tag);
int acl_set(const char *agent_id, const char *account_id, const char *api_scope, const char *resource_tag, Permission perm);
int acl_remove(const char *agent_id, const char *account_id, const char *api_scope);
int acl_load(const char *config_path);
int acl_save(const char *config_path);
void acl_free(void);

#endif
