#include "account_mgr.h"
#include "logger.h"
#include "config.h"
#include "crypto.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <jansson.h>

#define MAX_ACCOUNTS 32

static Account *accounts[MAX_ACCOUNTS];
static int account_count = 0;
static char secrets_path[256] = {0};

int account_mgr_init(const char *path) {
    strncpy(secrets_path, path, sizeof(secrets_path) - 1);

    // Initialize crypto
    char key_path[512];
    snprintf(key_path, sizeof(key_path), "%s/encryption.key", path);
    crypto_init(key_path);

    // Load existing accounts
    account_mgr_load();

    log_info("Account manager initialized with path: %s", secrets_path);
    return 0;
}

int account_mgr_load(void) {
    char path[512];
    snprintf(path, sizeof(path), "%s/accounts.enc", secrets_path);

    FILE *f = fopen(path, "r");
    if (!f) {
        log_info("No existing accounts file, starting fresh");
        return 0;
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
        log_error("Failed to parse accounts file: %s", error.text);
        return -1;
    }

    size_t index;
    json_t *obj;
    json_array_foreach(root, index, obj) {
        const char *id = json_string_value(json_object_get(obj, "id"));
        const char *email = json_string_value(json_object_get(obj, "google_email"));
        json_int_t expires = json_integer_value(json_object_get(obj, "token_expires"));

        Account *acct = malloc(sizeof(Account));
        memset(acct, 0, sizeof(Account));

        strncpy(acct->id, id ?: "", sizeof(acct->id) - 1);
        strncpy(acct->google_email, email ?: "", sizeof(acct->google_email) - 1);
        acct->token_expires = expires;

        // Decrypt access_token
        const char *enc_access = json_string_value(json_object_get(obj, "access_token"));
        if (enc_access) {
            unsigned char *decrypted = NULL;
            size_t dec_len = 0;
            if (crypto_decrypt(enc_access, strlen(enc_access), &decrypted, &dec_len) == 0) {
                acct->access_token = (char *)decrypted;
            }
        }

        // Decrypt refresh_token
        const char *enc_refresh = json_string_value(json_object_get(obj, "refresh_token"));
        if (enc_refresh) {
            unsigned char *decrypted = NULL;
            size_t dec_len = 0;
            if (crypto_decrypt(enc_refresh, strlen(enc_refresh), &decrypted, &dec_len) == 0) {
                acct->refresh_token = (char *)decrypted;
            }
        }

        accounts[account_count++] = acct;
    }

    json_decref(root);
    log_info("Loaded %d accounts from encrypted storage", account_count);
    return 0;
}

int account_mgr_add(Account *acct) {
    if (account_count >= MAX_ACCOUNTS) {
        log_error("Maximum number of accounts reached");
        return -1;
    }
    
    Account *new_acct = malloc(sizeof(Account));
    memcpy(new_acct, acct, sizeof(Account));
    
    // Duplicate strings
    new_acct->access_token = acct->access_token ? strdup(acct->access_token) : NULL;
    new_acct->refresh_token = acct->refresh_token ? strdup(acct->refresh_token) : NULL;
    
    accounts[account_count++] = new_acct;
    log_info("Account added: %s (%s)", new_acct->id, new_acct->google_email);
    
    return 0;
}

int account_mgr_remove(const char *account_id) {
    for (int i = 0; i < account_count; i++) {
        if (strcmp(accounts[i]->id, account_id) == 0) {
            free(accounts[i]->access_token);
            free(accounts[i]->refresh_token);
            free(accounts[i]);
            
            for (int j = i; j < account_count - 1; j++) {
                accounts[j] = accounts[j + 1];
            }
            account_count--;
            
            log_info("Account removed: %s", account_id);
            return 0;
        }
    }
    log_error("Account not found: %s", account_id);
    return -1;
}

int account_mgr_list(Account *out_accounts[], int *out_count) {
    *out_accounts = accounts;
    *out_count = account_count;
    return 0;
}

int account_mgr_get(const char *account_id, Account *acct) {
    for (int i = 0; i < account_count; i++) {
        if (strcmp(accounts[i]->id, account_id) == 0) {
            memcpy(acct, accounts[i], sizeof(Account));
            return 0;
        }
    }
    return -1;
}

int account_mgr_save(void) {
    char path[512];
    snprintf(path, sizeof(path), "%s/accounts.enc", secrets_path);

    json_t *root = json_array();

    for (int i = 0; i < account_count; i++) {
        json_t *obj = json_object();
        json_object_set_new(obj, "id", json_string(accounts[i]->id));
        json_object_set_new(obj, "google_email", json_string(accounts[i]->google_email));
        json_object_set_new(obj, "token_expires", json_integer(accounts[i]->token_expires));

        // Encrypt access_token
        if (accounts[i]->access_token && strlen(accounts[i]->access_token) > 0) {
            char *encrypted = NULL;
            size_t enc_len = 0;
            if (crypto_encrypt((unsigned char *)accounts[i]->access_token,
                              strlen(accounts[i]->access_token), &encrypted, &enc_len) == 0) {
                json_object_set_new(obj, "access_token", json_string(encrypted));
                crypto_free(encrypted);
            }
        }

        // Encrypt refresh_token
        if (accounts[i]->refresh_token && strlen(accounts[i]->refresh_token) > 0) {
            char *encrypted = NULL;
            size_t enc_len = 0;
            if (crypto_encrypt((unsigned char *)accounts[i]->refresh_token,
                              strlen(accounts[i]->refresh_token), &encrypted, &enc_len) == 0) {
                json_object_set_new(obj, "refresh_token", json_string(encrypted));
                crypto_free(encrypted);
            }
        }

        json_array_append_new(root, obj);
    }

    char *json_str = json_dumps(root, JSON_INDENT(2));
    FILE *f = fopen(path, "w");
    if (f) {
        fprintf(f, "%s", json_str);
        fclose(f);
        log_info("Accounts saved (encrypted) to: %s", path);
    } else {
        log_error("Failed to save accounts to: %s", path);
        free(json_str);
        json_decref(root);
        return -1;
    }

    free(json_str);
    json_decref(root);
    return 0;
}

void account_mgr_free(void) {
    for (int i = 0; i < account_count; i++) {
        free(accounts[i]->access_token);
        free(accounts[i]->refresh_token);
        free(accounts[i]);
    }
    account_count = 0;
    log_info("Account manager freed");
}
