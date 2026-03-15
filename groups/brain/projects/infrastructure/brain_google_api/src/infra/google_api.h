#ifndef GOOGLE_API_H
#define GOOGLE_API_H

#include <stdbool.h>

typedef enum {
    API_GMAIL = 0,
    API_DRIVE = 1,
    API_CALENDAR = 2,
    API_SHEETS = 3,
    API_DOCS = 4,
    API_SLIDES = 5,
    API_TASKS = 6,
    API_PEOPLE = 7,
    API_CLOUDSEARCH = 8
} GoogleAPI;

typedef enum {
    HTTP_GET,
    HTTP_POST,
    HTTP_PUT,
    HTTP_PATCH,
    HTTP_DELETE
} HTTPMethod;

int google_api_init(void);
char *google_api_call(const char *access_token, GoogleAPI api, const char *endpoint, HTTPMethod method, const char *json_body);
int google_api_gmail_list_messages(const char *access_token, const char *query, int max_results, char **response);
int google_api_gmail_send_message(const char *access_token, const char *to, const char *subject, const char *body, char **response);
int google_api_gmail_get_message(const char *access_token, const char *message_id, char **response);
int google_api_gmail_modify_message(const char *access_token, const char *message_id, const char *labels_add, const char *labels_remove, char **response);
int google_api_gmail_search(const char *access_token, const char *query, int max_results, char **response);
int google_api_gmail_create_label(const char *access_token, const char *name, char **response);
int google_api_drive_list_files(const char *access_token, const char *folder_id, char **response);
int google_api_drive_upload_file(const char *access_token, const char *parent_id, const char *name, const char *content_type, const char *content, char **response);
int google_api_drive_download_file(const char *access_token, const char *file_id, char **response);
int google_api_drive_create_folder(const char *access_token, const char *parent_id, const char *name, char **response);
int google_api_drive_delete_file(const char *access_token, const char *file_id);
int google_api_drive_move_file(const char *access_token, const char *file_id, const char *new_parent_id, char **response);
int google_api_calendar_list_events(const char *access_token, const char *calendar_id, const char *time_min, const char *time_max, char **response);
int google_api_calendar_create_event(const char *access_token, const char *calendar_id, const char *summary, const char *description, const char *start_time, const char *end_time, char **response);
int google_api_calendar_update_event(const char *access_token, const char *calendar_id, const char *event_id, const char *summary, const char *description, const char *start_time, const char *end_time, char **response);
int google_api_calendar_delete_event(const char *access_token, const char *calendar_id, const char *event_id);

// Google Docs API
int google_api_docs_create_document(const char *access_token, const char *title, char **response);
int google_api_docs_get_document(const char *access_token, const char *document_id, char **response);
int google_api_docs_update_document(const char *access_token, const char *document_id, const char *requests_json, char **response);

// Google Slides API
int google_api_slides_create_presentation(const char *access_token, const char *title, char **response);
int google_api_slides_get_presentation(const char *access_token, const char *presentation_id, char **response);
int google_api_slides_add_slide(const char *access_token, const char *presentation_id, int slide_index, char **response);

// Google Tasks API
int google_api_tasks_list_tasklists(const char *access_token, char **response);
int google_api_tasks_create_tasklist(const char *access_token, const char *title, char **response);
int google_api_tasks_list_tasks(const char *access_token, const char *tasklist_id, char **response);
int google_api_tasks_create_task(const char *access_token, const char *tasklist_id, const char *title, const char *due_date, char **response);
int google_api_tasks_update_task(const char *access_token, const char *tasklist_id, const char *task_id, const char *title, const char *due_date, char **response);
int google_api_tasks_delete_task(const char *access_token, const char *tasklist_id, const char *task_id);

// Google People API
int google_api_people_list_connections(const char *access_token, int page_size, char **response);
int google_api_people_get_profile(const char *access_token, char **response);
int google_api_people_create_contact(const char *access_token, const char *given_name, const char *family_name, const char *email, char **response);

// Google Sheets API
int google_api_sheets_create_spreadsheet(const char *access_token, const char *title, char **response);
int google_api_sheets_get_spreadsheet(const char *access_token, const char *spreadsheet_id, char **response);
int google_api_sheets_add_row(const char *access_token, const char *spreadsheet_id, const char *sheet_title, char **response);
int google_api_sheets_update_cell(const char *access_token, const char *spreadsheet_id, const char *sheet_title, int row, int col, const char *value, char **response);
int google_api_sheets_read_range(const char *access_token, const char *spreadsheet_id, const char *range, char **response);

void google_api_free(void);

#endif
