#include "mcp_protocol.h"
#include "logger.h"
#include <stdlib.h>
#include <string.h>
#include <jansson.h>

#define MAX_TOOLS 64

typedef struct {
    char name[64];
    char description[256];
    MCPMethodHandler handler;
} ToolEntry;

static ToolEntry tools[MAX_TOOLS];
static int tool_count = 0;

int mcp_protocol_init(void) {
    tool_count = 0;
    log_info("MCP protocol initialized");
    return 0;
}

int mcp_protocol_register_tool(const char *name, const char *description, MCPMethodHandler handler) {
    if (tool_count >= MAX_TOOLS) {
        log_error("Maximum number of tools reached");
        return -1;
    }
    
    strncpy(tools[tool_count].name, name, sizeof(tools[tool_count].name) - 1);
    strncpy(tools[tool_count].description, description, sizeof(tools[tool_count].description) - 1);
    tools[tool_count].handler = handler;
    tool_count++;
    
    log_info("Tool registered: %s", name);
    return 0;
}

int mcp_protocol_parse(const char *json_str, MCPRequest *req) {
    json_error_t error;
    json_t *root = json_loads(json_str, 0, &error);
    if (!root) {
        log_error("Failed to parse JSON: %s", error.text);
        return -1;
    }
    
    json_t *jsonrpc = json_object_get(root, "jsonrpc");
    if (!jsonrpc || !json_is_string(jsonrpc)) {
        json_decref(root);
        return -1;
    }
    
    json_t *method = json_object_get(root, "method");
    if (!method || !json_is_string(method)) {
        json_decref(root);
        return -1;
    }
    
    strncpy(req->method, json_string_value(method), sizeof(req->method) - 1);
    
    json_t *id = json_object_get(root, "id");
    if (id && json_is_string(id)) {
        strncpy(req->id, json_string_value(id), sizeof(req->id) - 1);
    } else {
        req->id[0] = '\0';
    }
    
    json_t *params = json_object_get(root, "params");
    if (params) {
        char *params_str = json_dumps(params, JSON_COMPACT);
        if (params_str) {
            req->params = strdup(params_str);
            free(params_str);
        }
    } else {
        req->params = NULL;
    }
    
    json_decref(root);
    return 0;
}

int mcp_protocol_build_response(const MCPResponse *resp, char **out_json) {
    json_t *root = json_object();
    json_object_set_new(root, "jsonrpc", json_string("2.0"));
    json_object_set_new(root, "id", json_string(resp->id));
    
    if (resp->error) {
        json_t *error = json_object();
        json_object_set_new(error, "code", json_integer(-32600));
        json_object_set_new(error, "message", json_string(resp->error));
        json_object_set_new(root, "error", error);
    } else if (resp->result) {
        json_t *result = json_loads(resp->result, 0, NULL);
        if (result) {
            json_object_set(root, "result", result);
        } else {
            json_object_set_new(root, "result", json_string(resp->result));
        }
    }
    
    *out_json = json_dumps(root, JSON_COMPACT);
    json_decref(root);
    return 0;
}

char *mcp_protocol_list_tools(void) {
    json_t *tools_array = json_array();
    for (int i = 0; i < tool_count; i++) {
        json_t *tool = json_object();
        json_object_set_new(tool, "name", json_string(tools[i].name));
        json_object_set_new(tool, "description", json_string(tools[i].description));
        json_array_append_new(tools_array, tool);
    }

    json_t *result = json_object();
    json_object_set_new(result, "tools", tools_array);

    char *out = json_dumps(result, JSON_INDENT(2));
    json_decref(result);
    return out;
}

void mcp_protocol_dispatch(const MCPRequest *req, MCPResponse *resp) {
    // Handle standard MCP methods
    if (strcmp(req->method, "tools/list") == 0) {
        resp->result = mcp_protocol_list_tools();
        return;
    }

    if (strcmp(req->method, "tools/call") == 0) {
        // Parse tools/call params: {"name": "tool_name", "arguments": "{\"action\":\"...\"}"}
        if (!req->params) {
            resp->error = "Missing params";
            return;
        }

        json_error_t error;
        json_t *params = json_loads(req->params, 0, &error);
        if (!params) {
            resp->error = "Invalid params JSON";
            return;
        }

        json_t *name_obj = json_object_get(params, "name");
        json_t *args_obj = json_object_get(params, "arguments");

        if (!name_obj || !json_is_string(name_obj)) {
            resp->error = "Missing or invalid 'name' parameter";
            json_decref(params);
            return;
        }

        const char *tool_name = json_string_value(name_obj);

        // Build internal request with the tool's arguments
        MCPRequest internal_req;
        memset(&internal_req, 0, sizeof(internal_req));
        strncpy(internal_req.method, tool_name, sizeof(internal_req.method) - 1);

        if (args_obj) {
            if (json_is_string(args_obj)) {
                // arguments is a JSON string
                internal_req.params = strdup(json_string_value(args_obj));
            } else if (json_is_object(args_obj)) {
                // arguments is already a JSON object
                char *args_str = json_dumps(args_obj, JSON_COMPACT);
                internal_req.params = args_str;
            }
        }

        // Find and call the tool
        for (int i = 0; i < tool_count; i++) {
            if (strcmp(tool_name, tools[i].name) == 0) {
                tools[i].handler(&internal_req, resp);
                free(internal_req.params);
                json_decref(params);
                return;
            }
        }

        resp->error = "Tool not found";
        free(internal_req.params);
        json_decref(params);
        return;
    }

    // Handle custom tool methods (legacy format)
    for (int i = 0; i < tool_count; i++) {
        if (strcmp(req->method, tools[i].name) == 0) {
            tools[i].handler(req, resp);
            return;
        }
    }

    resp->error = "Method not found";
}

void mcp_protocol_free(void) {
    for (int i = 0; i < tool_count; i++) {
        // Handlers are owned by caller
    }
    tool_count = 0;
    log_info("MCP protocol freed");
}
