#ifndef MCP_PROTOCOL_H
#define MCP_PROTOCOL_H

#include <stdbool.h>

typedef struct {
    char method[64];
    char id[64];
    char *params;
} MCPRequest;

typedef struct {
    char id[64];
    char *result;
    char *error;
} MCPResponse;

typedef void (*MCPMethodHandler)(const MCPRequest *req, MCPResponse *resp);

int mcp_protocol_init(void);
int mcp_protocol_register_tool(const char *name, const char *description, MCPMethodHandler handler);
int mcp_protocol_parse(const char *json, MCPRequest *req);
int mcp_protocol_build_response(const MCPResponse *resp, char **out_json);
char *mcp_protocol_list_tools(void);
void mcp_protocol_dispatch(const MCPRequest *req, MCPResponse *resp);
void mcp_protocol_free(void);

#endif
