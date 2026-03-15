#include "google_api_tool.h"

#include <string.h>
#include <jansson.h>

#include "acl.h"
#include "google_api.h"

static google_api_token_provider_t g_token_provider = NULL;

void google_api_tool_set_token_provider(google_api_token_provider_t provider) {
    g_token_provider = provider;
}

static const char *resolve_access_token(void) {
    return g_token_provider ? g_token_provider() : NULL;
}

static void handle_google_api(const MCPRequest *req, MCPResponse *resp) {
    json_t *params = json_loads(req->params ? req->params : "{}", 0, NULL);
    if (!params) {
        resp->error = "Invalid parameters";
        return;
    }

    const char *action = json_string_value(json_object_get(params, "action"));
    const char *account_id = json_string_value(json_object_get(params, "account_id"));
    const char *agent_id = json_string_value(json_object_get(params, "agent_id"));

    if (!action) {
        resp->error = "Missing 'action' parameter";
        json_decref(params);
        return;
    }

    const char *api_scope = NULL;
    if (strncmp(action, "gmail_", 6) == 0) api_scope = "gmail";
    else if (strncmp(action, "drive_", 6) == 0) api_scope = "drive";
    else if (strncmp(action, "calendar_", 9) == 0) api_scope = "calendar";
    else if (strncmp(action, "docs_", 5) == 0) api_scope = "docs";
    else if (strncmp(action, "slides_", 7) == 0) api_scope = "slides";
    else if (strncmp(action, "tasks_", 6) == 0) api_scope = "tasks";
    else if (strncmp(action, "sheets_", 7) == 0) api_scope = "sheets";
    else if (strncmp(action, "people_", 7) == 0) api_scope = "people";

    const char *effective_agent = (agent_id && strlen(agent_id) > 0) ? agent_id : "*";
    if (api_scope && !acl_check(effective_agent, account_id ?: "*", api_scope, "*")) {
        json_t *result = json_object();
        json_object_set_new(result, "error", json_string("ACL denied"));
        json_object_set_new(result, "allowed", json_boolean(false));
        resp->result = json_dumps(result, 0);
        json_decref(result);
        json_decref(params);
        return;
    }

    json_t *result = json_object();
    json_object_set_new(result, "action", json_string(action));
    json_object_set_new(result, "account_id", json_string(account_id ?: ""));

    if (strcmp(action, "gmail_list_messages") == 0 || strcmp(action, "gmail_get_message") == 0) {
        json_object_set_new(result, "messages", json_array());
    }
    else if (strcmp(action, "gmail_send_message") == 0) {
        const char *to = json_string_value(json_object_get(params, "to"));
        const char *subject = json_string_value(json_object_get(params, "subject"));
        const char *body = json_string_value(json_object_get(params, "body"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_gmail_send_message(access_token, to, subject, body, &api_response);
            if (ret == 0 && api_response) {
                json_t *api_result = json_loads(api_response, 0, NULL);
                if (api_result) {
                    json_t *msg_id = json_object_get(api_result, "id");
                    if (msg_id) json_object_set(result, "message_id", msg_id);
                    json_decref(api_result);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "gmail_search") == 0 || strcmp(action, "gmail_modify_message") == 0) {
        json_object_set_new(result, "success", json_boolean(true));
    }
    else if (strcmp(action, "gmail_create_label") == 0) {
        json_object_set_new(result, "label_id", json_string("mock-label-id"));
    }
    else if (strcmp(action, "drive_list_files") == 0 || strcmp(action, "drive_download_file") == 0) {
        json_object_set_new(result, "files", json_array());
    }
    else if (strcmp(action, "drive_upload_file") == 0 || strcmp(action, "drive_create_folder") == 0) {
        const char *name = json_string_value(json_object_get(params, "name"));
        const char *parent_id = json_string_value(json_object_get(params, "parent_id"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_drive_create_folder(access_token, parent_id, name ?: "untitled", &api_response);
            if (ret == 0 && api_response) {
                json_t *api_result = json_loads(api_response, 0, NULL);
                if (api_result) {
                    json_t *file_id = json_object_get(api_result, "id");
                    json_t *file_name = json_object_get(api_result, "name");
                    if (file_id) json_object_set(result, "file_id", file_id);
                    if (file_name) json_object_set(result, "name", file_name);
                    json_decref(api_result);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "drive_delete_file") == 0 || strcmp(action, "drive_move_file") == 0) {
        json_object_set_new(result, "success", json_boolean(true));
    }
    else if (strcmp(action, "calendar_list_events") == 0) {
        const char *calendar_id = json_string_value(json_object_get(params, "calendar_id"));
        const char *time_min = json_string_value(json_object_get(params, "time_min"));
        const char *time_max = json_string_value(json_object_get(params, "time_max"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_calendar_list_events(access_token, calendar_id ?: "primary", time_min, time_max, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "events", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to list events"));
            }
        }
    }
    else if (strcmp(action, "calendar_create_event") == 0 || strcmp(action, "calendar_update_event") == 0) {
        const char *summary = json_string_value(json_object_get(params, "summary"));
        const char *description = json_string_value(json_object_get(params, "description"));
        const char *start_time = json_string_value(json_object_get(params, "start_time"));
        const char *end_time = json_string_value(json_object_get(params, "end_time"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_calendar_create_event(access_token, "primary", summary, description, start_time, end_time, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "event", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to create event"));
            }
        }
    }
    else if (strcmp(action, "calendar_delete_event") == 0) {
        json_object_set_new(result, "success", json_boolean(true));
    }
    else if (strcmp(action, "docs_create_document") == 0 || strcmp(action, "docs_get_document") == 0) {
        const char *title = json_string_value(json_object_get(params, "title"));
        const char *document_id = json_string_value(json_object_get(params, "document_id"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = (strcmp(action, "docs_create_document") == 0)
                ? google_api_docs_create_document(access_token, title, &api_response)
                : google_api_docs_get_document(access_token, document_id, &api_response);
            if (ret == 0 && api_response) {
                json_t *api_result = json_loads(api_response, 0, NULL);
                if (api_result) {
                    json_t *doc_id = json_object_get(api_result, "documentId");
                    if (doc_id) json_object_set(result, "document_id", doc_id);
                    json_decref(api_result);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "docs_update_document") == 0) {
        const char *document_id = json_string_value(json_object_get(params, "document_id"));
        const char *requests_json = json_string_value(json_object_get(params, "requests"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_docs_update_document(access_token, document_id, requests_json ?: "{}", &api_response);
            if (ret == 0 && api_response) {
                json_object_set_new(result, "success", json_boolean(true));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "slides_create_presentation") == 0 || strcmp(action, "slides_get_presentation") == 0) {
        const char *title = json_string_value(json_object_get(params, "title"));
        const char *presentation_id = json_string_value(json_object_get(params, "presentation_id"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = (strcmp(action, "slides_create_presentation") == 0)
                ? google_api_slides_create_presentation(access_token, title, &api_response)
                : google_api_slides_get_presentation(access_token, presentation_id, &api_response);
            if (ret == 0 && api_response) {
                json_t *api_result = json_loads(api_response, 0, NULL);
                if (api_result) {
                    json_t *pres_id = json_object_get(api_result, "presentationId");
                    if (pres_id) json_object_set(result, "presentation_id", pres_id);
                    json_decref(api_result);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "slides_add_slide") == 0) {
        const char *presentation_id = json_string_value(json_object_get(params, "presentation_id"));
        int slide_index = json_integer_value(json_object_get(params, "slide_index"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_slides_add_slide(access_token, presentation_id, slide_index, &api_response);
            if (ret == 0 && api_response) {
                json_object_set_new(result, "success", json_boolean(true));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "tasks_list_tasklists") == 0 || strcmp(action, "tasks_list_tasks") == 0) {
        const char *tasklist_id = json_string_value(json_object_get(params, "tasklist_id"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = (strcmp(action, "tasks_list_tasklists") == 0)
                ? google_api_tasks_list_tasklists(access_token, &api_response)
                : google_api_tasks_list_tasks(access_token, tasklist_id, &api_response);
            if (ret == 0 && api_response) {
                json_object_set_new(result, "tasks", json_array());
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "tasks_create_tasklist") == 0 || strcmp(action, "tasks_create_task") == 0) {
        const char *title = json_string_value(json_object_get(params, "title"));
        const char *tasklist_id = json_string_value(json_object_get(params, "tasklist_id"));
        const char *due_date = json_string_value(json_object_get(params, "due_date"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = (strcmp(action, "tasks_create_tasklist") == 0)
                ? google_api_tasks_create_tasklist(access_token, title, &api_response)
                : google_api_tasks_create_task(access_token, tasklist_id, title, due_date, &api_response);
            if (ret == 0 && api_response) {
                json_t *api_result = json_loads(api_response, 0, NULL);
                if (api_result) {
                    json_t *id = json_object_get(api_result, "id");
                    if (id) json_object_set(result, "id", id);
                    json_decref(api_result);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "tasks_update_task") == 0) {
        const char *tasklist_id = json_string_value(json_object_get(params, "tasklist_id"));
        const char *task_id = json_string_value(json_object_get(params, "task_id"));
        const char *title = json_string_value(json_object_get(params, "title"));
        const char *due_date = json_string_value(json_object_get(params, "due_date"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_tasks_update_task(access_token, tasklist_id, task_id, title, due_date, &api_response);
            if (ret == 0 && api_response) {
                json_object_set_new(result, "success", json_boolean(true));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("API call failed"));
            }
        }
    }
    else if (strcmp(action, "tasks_delete_task") == 0) {
        const char *tasklist_id = json_string_value(json_object_get(params, "tasklist_id"));
        const char *task_id = json_string_value(json_object_get(params, "task_id"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            int ret = google_api_tasks_delete_task(access_token, tasklist_id, task_id);
            json_object_set_new(result, "success", json_boolean(ret == 0));
        }
    }
    else if (strcmp(action, "account_list") == 0) {
        json_object_set_new(result, "accounts", json_array());
    }
    else if (strcmp(action, "acl_check") == 0) {
        const char *resource_tag = json_string_value(json_object_get(params, "resource_tag"));
        bool allowed = acl_check(agent_id ?: "*", account_id ?: "*", api_scope ?: "*", resource_tag ?: "*");
        json_object_set_new(result, "allowed", json_boolean(allowed));
    }
    else if (strcmp(action, "acl_set") == 0) {
        const char *resource_tag = json_string_value(json_object_get(params, "resource_tag"));
        const char *permission = json_string_value(json_object_get(params, "permission"));
        Permission perm = PERM_READ;
        if (permission && strcmp(permission, "write") == 0) perm = PERM_WRITE;
        else if (permission && strcmp(permission, "admin") == 0) perm = PERM_ADMIN;
        acl_set(agent_id ?: "*", account_id ?: "*", api_scope ?: "*", resource_tag, perm);
        json_object_set_new(result, "success", json_boolean(true));
    }
    else if (strcmp(action, "sheets_create_spreadsheet") == 0) {
        const char *title = json_string_value(json_object_get(params, "title"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_sheets_create_spreadsheet(access_token, title, &api_response);
            if (ret == 0 && api_response) {
                json_t *parsed = json_loads(api_response, 0, NULL);
                if (parsed) {
                    json_object_set(result, "spreadsheet", parsed);
                    json_decref(parsed);
                }
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to create spreadsheet"));
            }
        }
    }
    else if (strcmp(action, "sheets_get_spreadsheet") == 0) {
        const char *spreadsheet_id = json_string_value(json_object_get(params, "spreadsheet_id"));
        const char *access_token = resolve_access_token();

        if (!access_token || !spreadsheet_id) {
            json_object_set_new(result, "error", json_string("Missing access_token or spreadsheet_id"));
        } else {
            char *api_response = NULL;
            int ret = google_api_sheets_get_spreadsheet(access_token, spreadsheet_id, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "spreadsheet", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to get spreadsheet"));
            }
        }
    }
    else if (strcmp(action, "sheets_read_range") == 0) {
        const char *spreadsheet_id = json_string_value(json_object_get(params, "spreadsheet_id"));
        const char *range = json_string_value(json_object_get(params, "range"));
        const char *access_token = resolve_access_token();

        if (!access_token || !spreadsheet_id || !range) {
            json_object_set_new(result, "error", json_string("Missing required parameters"));
        } else {
            char *api_response = NULL;
            int ret = google_api_sheets_read_range(access_token, spreadsheet_id, range, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "data", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to read range"));
            }
        }
    }
    else if (strcmp(action, "sheets_update_cell") == 0) {
        const char *spreadsheet_id = json_string_value(json_object_get(params, "spreadsheet_id"));
        const char *sheet_title = json_string_value(json_object_get(params, "sheet_title"));
        int row = json_integer_value(json_object_get(params, "row"));
        int col = json_integer_value(json_object_get(params, "col"));
        const char *value = json_string_value(json_object_get(params, "value"));
        const char *access_token = resolve_access_token();

        if (!access_token || !spreadsheet_id || !sheet_title || !value) {
            json_object_set_new(result, "error", json_string("Missing required parameters"));
        } else {
            char *api_response = NULL;
            int ret = google_api_sheets_update_cell(access_token, spreadsheet_id, sheet_title, row, col, value, &api_response);
            if (ret == 0 && api_response) {
                json_object_set_new(result, "success", json_boolean(true));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to update cell"));
            }
        }
    }
    else if (strcmp(action, "people_list_connections") == 0) {
        const char *access_token = resolve_access_token();
        int page_size = json_integer_value(json_object_get(params, "page_size"));
        if (page_size <= 0) page_size = 100;

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_people_list_connections(access_token, page_size, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "connections", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to list connections"));
            }
        }
    }
    else if (strcmp(action, "people_get_profile") == 0) {
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_people_get_profile(access_token, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "profile", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to get profile"));
            }
        }
    }
    else if (strcmp(action, "people_create_contact") == 0) {
        const char *given_name = json_string_value(json_object_get(params, "given_name"));
        const char *family_name = json_string_value(json_object_get(params, "family_name"));
        const char *email = json_string_value(json_object_get(params, "email"));
        const char *access_token = resolve_access_token();

        if (!access_token) {
            json_object_set_new(result, "error", json_string("No access token"));
        } else {
            char *api_response = NULL;
            int ret = google_api_people_create_contact(access_token, given_name ?: "", family_name ?: "", email, &api_response);
            if (ret == 0 && api_response) {
                json_object_set(result, "contact", json_loads(api_response, 0, NULL));
                free(api_response);
            } else {
                json_object_set_new(result, "error", json_string("Failed to create contact"));
            }
        }
    }
    else {
        json_object_set_new(result, "error", json_string("Unknown action"));
    }

    resp->result = json_dumps(result, 0);
    json_decref(result);
    json_decref(params);
}

void google_api_tool_register(void) {
    mcp_protocol_register_tool(
        "google_api",
        "Unified Google API: gmail_list_messages, gmail_send_message, drive_list_files, calendar_create_event, etc.",
        handle_google_api
    );
}
