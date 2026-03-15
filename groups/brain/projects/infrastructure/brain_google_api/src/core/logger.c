#include "logger.h"
#include <stdarg.h>
#include <string.h>

static LogLevel current_level = LOG_INFO;

void log_init(const char *level_str) {
    if (strcmp(level_str, "debug") == 0) current_level = LOG_DEBUG;
    else if (strcmp(level_str, "warn") == 0) current_level = LOG_WARN;
    else if (strcmp(level_str, "error") == 0) current_level = LOG_ERROR;
    else current_level = LOG_INFO;
}

static void log_write(LogLevel level, const char *level_str, const char *fmt, va_list args) {
    if (level < current_level) return;

    time_t now = time(NULL);
    char *ts = ctime(&now);
    ts[strlen(ts)-1] = '\0';

    fprintf(stderr, "[%s] [%s] ", ts, level_str);
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
    fflush(stderr);
}

void log_debug(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    log_write(LOG_DEBUG, "DEBUG", fmt, args);
    va_end(args);
}

void log_info(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    log_write(LOG_INFO, "INFO", fmt, args);
    va_end(args);
}

void log_warn(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    log_write(LOG_WARN, "WARN", fmt, args);
    va_end(args);
}

void log_error(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    log_write(LOG_ERROR, "ERROR", fmt, args);
    va_end(args);
}
