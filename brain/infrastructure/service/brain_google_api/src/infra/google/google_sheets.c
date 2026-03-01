#include "google_api.h"

#include <jansson.h>
#include <stdlib.h>
#include <string.h>

int google_api_sheets_create_spreadsheet(const char *access_token, const char *title, char **response) {
    json_t *root = json_object();
    json_object_set_new(root, "properties", json_object());
    json_object_set_new(json_object_get(root, "properties"), "title", json_string(title ? title : "New Spreadsheet"));

    char *json_str = json_dumps(root, 0);
    json_decref(root);
    char *result = google_api_call(access_token, API_SHEETS, "", HTTP_POST, json_str);
    free(json_str);

    *response = result;
    return result ? 0 : -1;
}

int google_api_sheets_get_spreadsheet(const char *access_token, const char *spreadsheet_id, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/%s", spreadsheet_id);
    char *result = google_api_call(access_token, API_SHEETS, endpoint, HTTP_GET, NULL);
    if (!result) return -1;
    *response = result;
    return 0;
}

int google_api_sheets_add_row(const char *access_token, const char *spreadsheet_id, const char *sheet_title, char **response) {
    char endpoint[256];
    snprintf(endpoint, sizeof(endpoint), "/%s/values/%s!A1:append", spreadsheet_id, sheet_title ? sheet_title : "Sheet1");

    json_t *root = json_object();
    json_object_set_new(root, "values", json_array());
    json_t *row = json_array();
    json_array_append_new(row, json_string(""));
    json_array_append_new(json_object_get(root, "values"), row);

    char *json_str = json_dumps(root, 0);
    json_decref(root);
    char *result = google_api_call(access_token, API_SHEETS, endpoint, HTTP_POST, json_str);
    free(json_str);

    *response = result;
    return result ? 0 : -1;
}

int google_api_sheets_update_cell(const char *access_token, const char *spreadsheet_id,
                                  const char *sheet_title, int row, int col, const char *value, char **response) {
    char endpoint[512];
    char *json_body = NULL;
    HTTPMethod method = HTTP_PUT;

    if (!spreadsheet_id || !sheet_title || !value) {
        return -1;
    }

    char cell[32];
    snprintf(cell, sizeof(cell), "%c%d", 'A' + (col > 0 ? col - 1 : 0), row);
    snprintf(endpoint, sizeof(endpoint), "/%s/values/%s!%s", spreadsheet_id, sheet_title, cell);

    json_body = malloc(strlen(value) + 128);
    snprintf(json_body, strlen(value) + 128, "{\"majorDimension\":\"ROWS\",\"values\":[[\"%s\"]]}", value);

    char *result = google_api_call(access_token, API_SHEETS, endpoint, method, json_body);
    free(json_body);
    *response = result;
    return result ? 0 : -1;
}

int google_api_sheets_read_range(const char *access_token, const char *spreadsheet_id,
                                 const char *range, char **response) {
    char endpoint[512];

    if (!spreadsheet_id || !range) {
        return -1;
    }

    snprintf(endpoint, sizeof(endpoint), "/%s/values/%s", spreadsheet_id, range);
    char *result = google_api_call(access_token, API_SHEETS, endpoint, HTTP_GET, NULL);
    *response = result;
    return result ? 0 : -1;
}
