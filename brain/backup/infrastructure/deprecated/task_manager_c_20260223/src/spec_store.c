/*
 * Spec Store — Spec 生命周期管理 (S1-S8 进度追踪)
 */

#include "task_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <sys/stat.h>
#include <unistd.h>

static const struct { SpecStage val; const char *str; } STAGE_MAP[] = {
    { SS_S1_ALIGNMENT,    "S1_alignment" },
    { SS_S2_REQUIREMENTS, "S2_requirements" },
    { SS_S3_RESEARCH,     "S3_research" },
    { SS_S4_ANALYSIS,     "S4_analysis" },
    { SS_S5_SOLUTION,     "S5_solution" },
    { SS_S6_TASKS,        "S6_tasks" },
    { SS_S7_VERIFICATION, "S7_verification" },
    { SS_S8_COMPLETE,     "S8_complete" },
    { SS_ARCHIVED,        "archived" },
    { 0, NULL }
};

static char *trim_ws(char *s) {
    if (!s) return s;
    while (*s && isspace((unsigned char)*s)) s++;
    size_t n = strlen(s);
    while (n > 0 && isspace((unsigned char)s[n - 1])) {
        s[n - 1] = '\0';
        n--;
    }
    return s;
}

static void strip_inline_comment(char *s) {
    if (!s) return;
    char *p = strchr(s, '#');
    if (p) *p = '\0';
}

static char *unquote(char *s) {
    if (!s) return s;
    size_t n = strlen(s);
    if (n >= 2 && ((s[0] == '"' && s[n - 1] == '"') || (s[0] == '\'' && s[n - 1] == '\''))) {
        s[n - 1] = '\0';
        s++;
    }
    return s;
}

static bool is_placeholder_owner(const char *owner) {
    if (!owner || !owner[0]) return true;
    char lower[TM_MAX_OWNER_LEN];
    size_t n = strlen(owner);
    if (n >= sizeof(lower)) n = sizeof(lower) - 1;
    for (size_t i = 0; i < n; i++) {
        lower[i] = (char)tolower((unsigned char)owner[i]);
    }
    lower[n] = '\0';

    static const char *bad[] = {
        "tbd", "todo", "pending", "unassigned", "unknown",
        "none", "null", "n/a", "na", "-", NULL
    };
    for (int i = 0; bad[i]; i++) {
        if (strcmp(lower, bad[i]) == 0) return true;
    }
    return false;
}

static bool is_explicit_agent_owner(const char *owner) {
    if (!owner || !owner[0]) return false;
    if (is_placeholder_owner(owner)) return false;
    return strncmp(owner, "agent_", 6) == 0;
}

/* Return codes:
 *   0  ok
 *  -5  missing 06_tasks.yaml
 *  -6  no task_id entries
 *  -7  some tasks missing explicit agent owner
 */
static int validate_tasks_artifact(const char *group, const char *spec_id) {
    char path[512];
    snprintf(path, sizeof(path), "/brain/groups/org/%s/spec/%s/06_tasks.yaml", group, spec_id);

    FILE *f = fopen(path, "r");
    if (!f) return -5;

    char line[1024];
    int total_tasks = 0;
    int assigned_tasks = 0;
    bool in_task = false;
    bool task_has_owner = false;

    while (fgets(line, sizeof(line), f)) {
        strip_inline_comment(line);
        char *p = trim_ws(line);
        if (!p || !p[0]) continue;

        bool is_task_id = false;
        char *v = NULL;
        if (strncmp(p, "- task_id:", 10) == 0) {
            is_task_id = true;
            v = p + 10;
        } else if (strncmp(p, "task_id:", 8) == 0) {
            is_task_id = true;
            v = p + 8;
        }

        if (is_task_id) {
            if (in_task) {
                total_tasks++;
                if (task_has_owner) assigned_tasks++;
            }
            in_task = false;
            task_has_owner = false;

            v = unquote(trim_ws(v));
            if (v && v[0]) {
                in_task = true;
            }
            continue;
        }

        if (!in_task) continue;

        if (strncmp(p, "owner:", 6) == 0 || strncmp(p, "- owner:", 8) == 0) {
            char *ov = (p[0] == '-') ? (p + 8) : (p + 6);
            ov = unquote(trim_ws(ov));
            if (is_explicit_agent_owner(ov)) {
                task_has_owner = true;
            }
        }
    }

    if (in_task) {
        total_tasks++;
        if (task_has_owner) assigned_tasks++;
    }
    fclose(f);

    if (total_tasks == 0) return -6;
    if (assigned_tasks < total_tasks) return -7;
    return 0;
}

const char *spec_stage_str(SpecStage s) {
    for (int i = 0; STAGE_MAP[i].str; i++)
        if (STAGE_MAP[i].val == s) return STAGE_MAP[i].str;
    return "S1_alignment";
}

SpecStage spec_stage_from_str(const char *s) {
    if (!s) return SS_S1_ALIGNMENT;
    for (int i = 0; STAGE_MAP[i].str; i++)
        if (strcmp(s, STAGE_MAP[i].str) == 0) return STAGE_MAP[i].val;
    return SS_S1_ALIGNMENT;
}

static json_t *spec_to_json(const SpecRecord *r) {
    json_t *obj = json_object();
    json_object_set_new(obj, "spec_id", json_string(r->spec_id));
    json_object_set_new(obj, "title", json_string(r->title));
    json_object_set_new(obj, "group", json_string(r->group));
    json_object_set_new(obj, "owner", json_string(r->owner));
    json_object_set_new(obj, "stage", json_string(spec_stage_str(r->stage)));
    json_object_set_new(obj, "created_at", json_string(r->created_at));
    json_object_set_new(obj, "updated_at", json_string(r->updated_at));
    return obj;
}

static void spec_from_json(SpecRecord *r, const char *id, json_t *obj) {
    memset(r, 0, sizeof(*r));
    r->active = true;
    snprintf(r->spec_id, sizeof(r->spec_id), "%s", id);

    const char *v;
    if ((v = json_string_value(json_object_get(obj, "title"))))
        snprintf(r->title, sizeof(r->title), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "group"))))
        snprintf(r->group, sizeof(r->group), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "owner"))))
        snprintf(r->owner, sizeof(r->owner), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "stage"))))
        r->stage = spec_stage_from_str(v);
    if ((v = json_string_value(json_object_get(obj, "created_at"))))
        snprintf(r->created_at, sizeof(r->created_at), "%s", v);
    if ((v = json_string_value(json_object_get(obj, "updated_at"))))
        snprintf(r->updated_at, sizeof(r->updated_at), "%s", v);
}

void spec_store_init(SpecStore *s, const char *data_dir) {
    memset(s, 0, sizeof(*s));
    snprintf(s->data_path, sizeof(s->data_path), "%s/specs.json", data_dir);
    pthread_mutex_init(&s->mu, NULL);
}

int spec_store_load(SpecStore *s) {
    pthread_mutex_lock(&s->mu);
    s->count = 0;

    FILE *f = fopen(s->data_path, "r");
    if (!f) { pthread_mutex_unlock(&s->mu); return 0; }

    json_error_t err;
    json_t *root = json_loadf(f, 0, &err);
    fclose(f);
    if (!root) { pthread_mutex_unlock(&s->mu); return -1; }

    json_t *specs = json_object_get(root, "specs");
    if (json_is_object(specs)) {
        const char *key;
        json_t *val;
        json_object_foreach(specs, key, val) {
            if (s->count >= TM_MAX_SPECS) break;
            spec_from_json(&s->specs[s->count], key, val);
            s->count++;
        }
    }

    json_decref(root);
    pthread_mutex_unlock(&s->mu);
    return s->count;
}

int spec_store_flush(SpecStore *s) {
    json_t *specs_obj = json_object();
    for (int i = 0; i < s->count; i++) {
        if (!s->specs[i].active) continue;
        json_object_set_new(specs_obj, s->specs[i].spec_id, spec_to_json(&s->specs[i]));
    }

    json_t *root = json_object();
    json_object_set_new(root, "specs", specs_obj);

    char tmp[520];
    snprintf(tmp, sizeof(tmp), "%s.tmp", s->data_path);

    char dir[512];
    snprintf(dir, sizeof(dir), "%s", s->data_path);
    char *slash = strrchr(dir, '/');
    if (slash) { *slash = '\0'; mkdir(dir, 0755); }

    int rc = json_dump_file(root, tmp, JSON_INDENT(2) | JSON_ENSURE_ASCII);
    json_decref(root);
    if (rc != 0) return -1;
    if (rename(tmp, s->data_path) != 0) return -1;
    return 0;
}

static void mkdirs(const char *path) {
    char buf[512];
    snprintf(buf, sizeof(buf), "%s", path);
    for (char *p = buf + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(buf, 0755);
            *p = '/';
        }
    }
    mkdir(buf, 0755);
}

int spec_store_create(SpecStore *s, const char *spec_id, const char *title,
                       const char *group, const char *owner) {
    pthread_mutex_lock(&s->mu);

    /* duplicate check */
    for (int i = 0; i < s->count; i++) {
        if (s->specs[i].active && strcmp(s->specs[i].spec_id, spec_id) == 0) {
            pthread_mutex_unlock(&s->mu);
            return -1;
        }
    }
    if (s->count >= TM_MAX_SPECS) {
        pthread_mutex_unlock(&s->mu);
        return -2;
    }

    /* create directory skeleton */
    char dir[512];
    snprintf(dir, sizeof(dir), "/brain/groups/org/%s/spec/%s", group, spec_id);
    mkdirs(dir);

    char sub[512];
    snprintf(sub, sizeof(sub), "%s/agent_output_raw/plan", dir);
    mkdirs(sub);

    /* generate 00_index.yaml */
    char path[512];
    snprintf(path, sizeof(path), "%s/00_index.yaml", dir);
    FILE *f = fopen(path, "w");
    if (f) {
        char ts[32]; now_iso(ts, sizeof(ts));
        fprintf(f, "spec_id: %s\ntitle: %s\nstatus: S1-alignment\n"
                   "owner: %s\ncreated_at: %s\ngroup: %s\n",
                spec_id, title, owner, ts, group);
        fclose(f);
    }

    /* generate 01-08 skeleton files */
    static const char *stage_names[] = {
        "alignment", "requirements", "research", "analysis",
        "solution", "tasks", "verification", "complete"
    };
    for (int i = 0; i < 8; i++) {
        snprintf(path, sizeof(path), "%s/%02d_%s.yaml", dir, i + 1, stage_names[i]);
        if (access(path, F_OK) != 0) {
            f = fopen(path, "w");
            if (f) {
                if (i == 5) {
                    /* S6 bootstrap: kickoff task list is mandatory from project intake. */
                    fprintf(f,
                            "# %s S6: tasks\n"
                            "tasks:\n"
                            "  - task_id: \"%s-T001\"\n"
                            "    title: \"Project intake baseline\"\n"
                            "    owner: \"%s\"\n"
                            "    priority: high\n"
                            "    depends_on: []\n"
                            "    acceptance_criteria:\n"
                            "      - \"project kickoff task recorded\"\n"
                            "      - \"task list will be refined before S7\"\n",
                            spec_id, spec_id, owner);
                } else {
                    fprintf(f, "# %s S%d: %s\n", spec_id, i + 1, stage_names[i]);
                }
                fclose(f);
            }
        }
    }

    /* persist record */
    SpecRecord *r = &s->specs[s->count];
    memset(r, 0, sizeof(*r));
    r->active = true;
    snprintf(r->spec_id, sizeof(r->spec_id), "%s", spec_id);
    snprintf(r->title, sizeof(r->title), "%s", title);
    snprintf(r->group, sizeof(r->group), "%s", group);
    snprintf(r->owner, sizeof(r->owner), "%s", owner);
    r->stage = SS_S1_ALIGNMENT;
    now_iso(r->created_at, sizeof(r->created_at));
    now_iso(r->updated_at, sizeof(r->updated_at));
    s->count++;

    spec_store_flush(s);
    pthread_mutex_unlock(&s->mu);
    return 0;
}

int spec_store_advance(SpecStore *s, const char *spec_id, const char *target_stage, bool force) {
    pthread_mutex_lock(&s->mu);

    SpecRecord *r = NULL;
    for (int i = 0; i < s->count; i++) {
        if (s->specs[i].active && strcmp(s->specs[i].spec_id, spec_id) == 0) {
            r = &s->specs[i];
            break;
        }
    }
    if (!r) { pthread_mutex_unlock(&s->mu); return -1; /* not found */ }

    SpecStage target = spec_stage_from_str(target_stage);

    if (!force) {
        if ((int)target <= (int)r->stage) {
            pthread_mutex_unlock(&s->mu);
            return -3; /* cannot go backward */
        }
        if ((int)target > (int)r->stage + 1) {
            pthread_mutex_unlock(&s->mu);
            return -4; /* cannot skip */
        }
    }

    if ((int)target >= (int)SS_S6_TASKS) {
        int vr = validate_tasks_artifact(r->group, r->spec_id);
        if (vr != 0) {
            pthread_mutex_unlock(&s->mu);
            return vr;
        }
    }

    r->stage = target;
    now_iso(r->updated_at, sizeof(r->updated_at));
    spec_store_flush(s);
    pthread_mutex_unlock(&s->mu);
    return 0;
}

json_t *spec_store_query(SpecStore *s, json_t *filters) {
    pthread_mutex_lock(&s->mu);
    json_t *arr = json_array();

    const char *by = json_string_value(json_object_get(filters, "by"));
    if (!by) by = "all";

    for (int i = 0; i < s->count; i++) {
        SpecRecord *r = &s->specs[i];
        if (!r->active) continue;

        bool match = true;
        if (strcmp(by, "id") == 0) {
            const char *sid = json_string_value(json_object_get(filters, "spec_id"));
            match = sid && strcmp(r->spec_id, sid) == 0;
        } else if (strcmp(by, "group") == 0) {
            const char *grp = json_string_value(json_object_get(filters, "group"));
            match = grp && strcmp(r->group, grp) == 0;
        } else if (strcmp(by, "stage") == 0) {
            const char *stg = json_string_value(json_object_get(filters, "stage"));
            match = stg && strcmp(spec_stage_str(r->stage), stg) == 0;
        }

        if (match) json_array_append_new(arr, spec_to_json(r));
    }

    pthread_mutex_unlock(&s->mu);
    return arr;
}

SpecRecord *spec_store_get(SpecStore *s, const char *spec_id) {
    for (int i = 0; i < s->count; i++) {
        if (s->specs[i].active && strcmp(s->specs[i].spec_id, spec_id) == 0)
            return &s->specs[i];
    }
    return NULL;
}
