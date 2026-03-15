#pragma once
// Simple JSON structured logger (spdlog-compatible interface)
// Writes to stderr in JSON format, no exceptions, no iostream

#include <cstdio>
#include <ctime>
#include <string>
#include <string_view>

enum class LogLevel { DEBUG = 0, INFO = 1, WARN = 2, ERROR = 3 };

namespace logger_internal {

inline const char* LevelName(LogLevel l) {
  switch (l) {
    case LogLevel::DEBUG: return "DEBUG";
    case LogLevel::INFO:  return "INFO";
    case LogLevel::WARN:  return "WARN";
    case LogLevel::ERROR: return "ERROR";
  }
  return "INFO";
}

inline LogLevel g_level = LogLevel::INFO;

inline void Log(LogLevel level, std::string_view component, std::string_view msg) {
  if (level < g_level) return;
  char ts[32];
  time_t now = time(nullptr);
  struct tm tm_info;
  gmtime_r(&now, &tm_info);
  strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &tm_info);

  // Escape msg for JSON (basic: escape backslash and double-quote)
  std::string escaped;
  escaped.reserve(msg.size());
  for (char c : msg) {
    if (c == '"') escaped += "\\\"";
    else if (c == '\\') escaped += "\\\\";
    else if (c == '\n') escaped += "\\n";
    else escaped += c;
  }

  fprintf(stderr, "{\"ts\":\"%s\",\"level\":\"%s\",\"component\":\"%.*s\",\"msg\":\"%s\"}\n",
          ts, LevelName(level),
          static_cast<int>(component.size()), component.data(),
          escaped.c_str());
}

}  // namespace logger_internal

inline void SetLogLevel(LogLevel l) { logger_internal::g_level = l; }

#define LOG_DEBUG(comp, msg) logger_internal::Log(LogLevel::DEBUG, comp, msg)
#define LOG_INFO(comp, msg)  logger_internal::Log(LogLevel::INFO,  comp, msg)
#define LOG_WARN(comp, msg)  logger_internal::Log(LogLevel::WARN,  comp, msg)
#define LOG_ERROR(comp, msg) logger_internal::Log(LogLevel::ERROR, comp, msg)

// Format helpers (avoids snprintf overhead when level filtered)
#include <cstdarg>
inline std::string LogFmt(const char* fmt, ...) {
  char buf[1024];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  return buf;
}
