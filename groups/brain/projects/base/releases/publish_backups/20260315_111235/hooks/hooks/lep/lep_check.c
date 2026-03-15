/*
 * LEP Check - 轻量 C 版本
 *
 * 快速路径检查，不解析 YAML（复杂逻辑由 Python daemon 处理）
 *
 * 功能：
 * - 检查保护路径 (G-SCOP)
 * - 检查删除操作 (G-DELETE-BACKUP)
 * - Bash 命令白名单守卫 (bash_guard)
 * - 角色感知：读取 BRAIN_AGENT_ROLE 环境变量，devops 可写 infrastructure
 *
 * 环境变量（由 agentctl 注入）：
 *   BRAIN_AGENT_ROLE:  角色名 (pmo, architect, dev, devops, qa, frontdesk)
 *   BRAIN_AGENT_GROUP: 组名
 *   BRAIN_SCOPE_PATH:  基础 scope 路径
 *
 * 用法:
 *   lep_check protected <path>
 *   lep_check delete <path>
 *   lep_check move <src> <dst>
 *   lep_check bash_guard <full_command>
 *
 * 返回:
 *   0 = pass
 *   1 = block
 *   2 = warn
 *
 * 编译: gcc -O2 -o lep_check lep_check.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* ============================================================
 * Universal protected paths - ALL roles blocked from writing
 * ============================================================ */
static const char *UNIVERSAL_PROTECTED[] = {
    "/brain/",                   /* published brain tree: never edit directly */
    "/xkagent_infra/brain/",     /* workspace path to published brain tree */
    NULL
};

/* ============================================================
 * Legacy role-specific exceptions retained for non-universal paths.
 *
 * Note:
 * - /brain/** and /xkagent_infra/brain/** are now universally protected
 * - the exception tables below no longer apply to the published brain tree
 * - keep them only for future narrowing or for non-published prefixes
 * ============================================================ */

/* Legacy extended protected paths (currently shadowed by universal /brain guards) */
static const char *EXTENDED_PROTECTED[] = {
    "/brain/base/spec/",         /* G-GATE-SCOP: spec 目录 */
    "/brain/infrastructure/",    /* infra 目录 */
    NULL
};

/* architect 可写的 spec 子路径 */
static const char *ARCHITECT_WRITE_EXCEPTIONS[] = {
    "/brain/base/spec/templates/",
    "/brain/base/knowledge/",
    NULL
};

/* devops 可写的 infra 路径 */
static const char *DEVOPS_WRITE_EXCEPTIONS[] = {
    "/brain/infrastructure/",
    NULL
};

/* brain-manager 可写的 infra 路径 */
static const char *BRAIN_MANAGER_WRITE_EXCEPTIONS[] = {
    "/brain/infrastructure/service/agent_abilities/",
    "/brain/base/hooks/",
    NULL
};

/* 删除例外路径 */
static const char *DELETE_EXCEPTIONS[] = {
    "/tmp/",
    "build/",
    "__pycache__/",
    ".pyc",
    ".pyo",
    "node_modules/",
    ".git/objects/",
    NULL
};

/*
 * Bash 命令白名单：只有这些命令前缀允许涉及保护路径
 * 其余一律 BLOCK（宁可误拦也不漏放）
 */
static const char *READ_ONLY_COMMANDS[] = {
    "cat ",    "head ",   "tail ",    "less ",
    "more ",   "grep ",   "rg ",      "ag ",
    "find ",   "ls ",     "ls\t",     "tree ",
    "wc ",     "file ",   "stat ",    "md5sum ",
    "sha256sum ", "sha1sum ", "diff ",
    "readlink ", "realpath ", "basename ", "dirname ",
    "test ",   "[ ",
    NULL
};

/* 检查路径是否以某前缀开头 */
static int starts_with(const char *str, const char *prefix) {
    return strncmp(str, prefix, strlen(prefix)) == 0;
}

/* 检查路径是否包含某子串 */
static int contains(const char *str, const char *substr) {
    return strstr(str, substr) != NULL;
}

/* 检查字符串是否完全等于 */
static int equals(const char *str, const char *target) {
    return strcmp(str, target) == 0;
}

/* 获取当前角色 */
static const char *get_role(void) {
    const char *role = getenv("BRAIN_AGENT_ROLE");
    return role ? role : "default";
}

/* 检查角色是否有某路径的写入豁免 */
static int role_has_write_exception(const char *role, const char *path) {
    /* architect can write spec/templates/ and knowledge/ */
    if (strcmp(role, "architect") == 0) {
        for (int i = 0; ARCHITECT_WRITE_EXCEPTIONS[i] != NULL; i++) {
            if (starts_with(path, ARCHITECT_WRITE_EXCEPTIONS[i])) {
                return 1;
            }
        }
    }

    /* devops can write infrastructure/ */
    if (strcmp(role, "devops") == 0) {
        for (int i = 0; DEVOPS_WRITE_EXCEPTIONS[i] != NULL; i++) {
            if (starts_with(path, DEVOPS_WRITE_EXCEPTIONS[i])) {
                return 1;
            }
        }
    }

    /* brain-manager can write hooks build system */
    if (strcmp(role, "brain-manager") == 0) {
        for (int i = 0; BRAIN_MANAGER_WRITE_EXCEPTIONS[i] != NULL; i++) {
            if (starts_with(path, BRAIN_MANAGER_WRITE_EXCEPTIONS[i])) {
                return 1;
            }
        }
    }

    return 0;
}

/* G-SCOP: 检查是否是保护路径 */
static int check_protected(const char *path) {
    const char *role = get_role();

    /* 1. Universal protections - no role can bypass */
    for (int i = 0; UNIVERSAL_PROTECTED[i] != NULL; i++) {
        if (starts_with(path, UNIVERSAL_PROTECTED[i]) || equals(path, UNIVERSAL_PROTECTED[i])) {
            fprintf(stderr, "BLOCK: Universal protected path: %s\n", UNIVERSAL_PROTECTED[i]);
            fprintf(stderr, "  Role: %s | No role can write to the published /brain tree directly.\n", role);
            return 1;  /* block */
        }
    }

    /* 2. Extended protections - check role exceptions */
    for (int i = 0; EXTENDED_PROTECTED[i] != NULL; i++) {
        if (starts_with(path, EXTENDED_PROTECTED[i]) || equals(path, EXTENDED_PROTECTED[i])) {
            /* Check if this role has a write exception */
            if (role_has_write_exception(role, path)) {
                /* Role-specific exception: allow */
                return 0;  /* pass */
            }
            fprintf(stderr, "BLOCK: Protected path: %s\n", EXTENDED_PROTECTED[i]);
            fprintf(stderr, "  Role: %s | Use a role with write access or request PMO approval.\n", role);
            return 1;  /* block */
        }
    }

    return 0;  /* pass */
}

/* G-DELETE-BACKUP: 检查删除操作 */
static int check_delete(const char *path) {
    /* 保护路径禁止删除 (G-SCOP 优先于 G-DELETE-BACKUP) */
    int protected_result = check_protected(path);
    if (protected_result == 1) {
        return 1;  /* block */
    }

    /* 检查例外路径 */
    for (int i = 0; DELETE_EXCEPTIONS[i] != NULL; i++) {
        if (starts_with(path, DELETE_EXCEPTIONS[i]) ||
            contains(path, DELETE_EXCEPTIONS[i])) {
            return 0;  /* pass - 例外路径无需备份 */
        }
    }

    /* 非例外路径，返回警告 */
    fprintf(stderr, "WARN: G-DELETE-BACKUP requires backup before delete: %s\n", path);
    return 2;  /* warn */
}

/* G-SCOP: 检查移动操作（源或目标在保护路径则 block） */
static int check_move(const char *src, const char *dst) {
    int src_result = check_protected(src);
    if (src_result == 1) {
        fprintf(stderr, "  Cannot move FROM protected path.\n");
        return 1;
    }

    int dst_result = check_protected(dst);
    if (dst_result == 1) {
        fprintf(stderr, "  Cannot move INTO protected path.\n");
        return 1;
    }

    return 0;  /* pass */
}

/*
 * bash_guard: Bash 命令涉及保护路径时的白名单检查 (role-aware)
 */
static int check_bash_guard(const char *command) {
    const char *role = get_role();

    /* 先检查 universal + extended protected paths */
    const char *matched_protected = NULL;

    /* Check universal first */
    for (int i = 0; UNIVERSAL_PROTECTED[i] != NULL; i++) {
        if (contains(command, UNIVERSAL_PROTECTED[i])) {
            matched_protected = UNIVERSAL_PROTECTED[i];
            break;
        }
    }

    /* If no universal match, check extended (with role exceptions) */
    if (matched_protected == NULL) {
        for (int i = 0; EXTENDED_PROTECTED[i] != NULL; i++) {
            if (contains(command, EXTENDED_PROTECTED[i])) {
                /* Check if role has exception for this path */
                if (role_has_write_exception(role, EXTENDED_PROTECTED[i])) {
                    continue;  /* Role exception: skip this protection */
                }
                matched_protected = EXTENDED_PROTECTED[i];
                break;
            }
        }
    }

    if (matched_protected == NULL) {
        return 0;  /* 命令不涉及保护路径，pass */
    }

    /*
     * 命令涉及保护路径 → 拆分管道段，逐段检查
     * 只有包含保护路径的段才需要是只读命令
     */
    char *cmd_copy = strdup(command);
    if (!cmd_copy) return 1;  /* malloc 失败，保守 block */

    char *segment = cmd_copy;
    char *pipe_pos;
    int blocked = 0;

    while (segment != NULL) {
        /* 找下一个管道符 | 或链接符 && ; */
        pipe_pos = NULL;
        char *p1 = strstr(segment, "|");
        char *p2 = strstr(segment, "&&");
        char *p3 = strstr(segment, ";");

        /* 取最近的分隔符 */
        pipe_pos = p1;
        if (p2 && (!pipe_pos || p2 < pipe_pos)) pipe_pos = p2;
        if (p3 && (!pipe_pos || p3 < pipe_pos)) pipe_pos = p3;

        char *next_segment = NULL;
        if (pipe_pos) {
            /* 跳过分隔符本身 */
            if (starts_with(pipe_pos, "&&")) {
                *pipe_pos = '\0';
                next_segment = pipe_pos + 2;
            } else {
                *pipe_pos = '\0';
                next_segment = pipe_pos + 1;
            }
        }

        /* 跳过 segment 前导空格 */
        while (*segment && isspace((unsigned char)*segment)) segment++;

        /* 这个段是否涉及保护路径（考虑角色豁免）？ */
        int seg_has_protected = 0;
        for (int i = 0; UNIVERSAL_PROTECTED[i] != NULL; i++) {
            if (contains(segment, UNIVERSAL_PROTECTED[i])) {
                seg_has_protected = 1;
                break;
            }
        }
        if (!seg_has_protected) {
            for (int i = 0; EXTENDED_PROTECTED[i] != NULL; i++) {
                if (contains(segment, EXTENDED_PROTECTED[i])) {
                    if (!role_has_write_exception(role, EXTENDED_PROTECTED[i])) {
                        seg_has_protected = 1;
                    }
                    break;
                }
            }
        }

        if (seg_has_protected) {
            /* 检查这个段的命令是否在只读白名单中 */
            int is_readonly = 0;
            for (int i = 0; READ_ONLY_COMMANDS[i] != NULL; i++) {
                if (starts_with(segment, READ_ONLY_COMMANDS[i])) {
                    is_readonly = 1;
                    break;
                }
            }

            if (!is_readonly) {
                fprintf(stderr, "BLOCK: Non-read command on protected path: %s\n", matched_protected);
                fprintf(stderr, "  Role: %s | Segment: %s\n", role, segment);
                fprintf(stderr, "  Only read-only commands (cat, ls, grep, etc.) are allowed.\n");
                blocked = 1;
                break;
            }
        }

        segment = next_segment;
    }

    free(cmd_copy);
    return blocked ? 1 : 0;
}

/* 打印用法 */
static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s <check_type> <path> [dst_path]\n", prog);
    fprintf(stderr, "  check_type: protected | delete | move | bash_guard\n");
    fprintf(stderr, "  move requires both src and dst path\n");
    fprintf(stderr, "  bash_guard takes the full command string\n");
    fprintf(stderr, "  Returns: 0=pass, 1=block, 2=warn\n");
    fprintf(stderr, "  Env: BRAIN_AGENT_ROLE (role-aware scope)\n");
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        usage(argv[0]);
        return 1;
    }

    const char *check_type = argv[1];
    const char *path = argv[2];

    if (strcmp(check_type, "protected") == 0) {
        return check_protected(path);
    } else if (strcmp(check_type, "delete") == 0) {
        return check_delete(path);
    } else if (strcmp(check_type, "move") == 0) {
        if (argc < 4) {
            fprintf(stderr, "move requires: %s move <src> <dst>\n", argv[0]);
            return 1;
        }
        return check_move(path, argv[3]);
    } else if (strcmp(check_type, "bash_guard") == 0) {
        return check_bash_guard(path);
    } else {
        fprintf(stderr, "Unknown check type: %s\n", check_type);
        usage(argv[0]);
        return 1;
    }
}
