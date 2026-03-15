#ifndef ACCOUNT_MGR_H
#define ACCOUNT_MGR_H

#include <stdbool.h>
#include <time.h>

typedef struct {
    char id[64];
    char google_email[128];
    char *access_token;
    char *refresh_token;
    time_t token_expires;
    char **scopes;
    int scope_count;
} Account;

int account_mgr_init(const char *secrets_path);
int account_mgr_add(Account *acct);
int account_mgr_remove(const char *account_id);
int account_mgr_list(Account *accounts[], int *count);
int account_mgr_get(const char *account_id, Account *acct);
int account_mgr_save(void);
int account_mgr_load(void);
void account_mgr_free(void);

#endif
