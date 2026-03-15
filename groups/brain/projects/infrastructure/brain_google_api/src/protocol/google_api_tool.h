#ifndef GOOGLE_API_TOOL_H
#define GOOGLE_API_TOOL_H

#include "mcp_protocol.h"

typedef const char *(*google_api_token_provider_t)(void);

void google_api_tool_set_token_provider(google_api_token_provider_t provider);
void google_api_tool_register(void);

#endif
