#ifndef OAUTH2_H
#define OAUTH2_H

#include <stdbool.h>
#include <time.h>

typedef struct {
    char client_id[256];
    char client_secret[256];
    char redirect_uri[256];
    char *auth_url;
    char *token_url;
} OAuth2Config;

typedef struct {
    char *access_token;
    char *refresh_token;
    int expires_in;
    time_t token_obtained;
} OAuth2Token;

int oauth2_init(OAuth2Config *cfg, const char *client_id, const char *client_secret);
char *oauth2_get_auth_url(const char *account_id);
int oauth2_exchange_code(const char *code, OAuth2Token *token);
int oauth2_refresh(const char *refresh_token, OAuth2Token *token);
void oauth2_token_free(OAuth2Token *token);
void oauth2_free(void);

#endif
