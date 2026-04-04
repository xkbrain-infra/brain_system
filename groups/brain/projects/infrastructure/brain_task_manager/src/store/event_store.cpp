#include "brain_task_manager/store/event_store.h"
#include "brain_task_manager/core/yaml_util.h"
#include <fstream>
#include <sys/stat.h>
#include <cerrno>
#include <cstring>

// 递归创建目录（等价于 mkdir -p）
static bool MkdirP(const std::string& path) {
  for (size_t pos = 1; pos < path.size(); ++pos) {
    if (path[pos] == '/') {
      std::string partial = path.substr(0, pos);
      if (mkdir(partial.c_str(), 0755) != 0 && errno != EEXIST) return false;
    }
  }
  if (mkdir(path.c_str(), 0755) != 0 && errno != EEXIST) return false;
  return true;
}

EventStore::EventStore(const std::string& data_dir) : data_dir_(data_dir) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
}

std::string EventStore::EventFilePath(const std::string& group,
                                       const std::string& project_id) const {
  return ProjectDataDir(data_dir_, group, project_id) + "events.json";
}

bool EventStore::Append(const TaskEvent& event) {
  std::lock_guard<std::mutex> lock(mu_);

  std::string dir = ProjectDataDir(data_dir_, event.group, event.project_id);
  if (!MkdirP(dir)) {
    LOG_ERROR("event_store", LogFmt("failed to create dir: %s", dir.c_str()));
    return false;
  }

  std::string file_path = dir + "events.yaml";

  // 读取现有事件列表（若文件存在）
  json existing;
  existing["events"] = json::array();
  {
    std::ifstream f(file_path);
    if (f.is_open()) {
      json j = YamlToJson(YAML::Load(f));
      if (!j.is_null() && j.contains("events") && j["events"].is_array()) {
        existing = j;
      }
    }
  }

  // 追加新事件
  existing["events"].push_back(event.to_json());

  // 原子写入
  std::string tmp_path = file_path + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) {
      LOG_ERROR("event_store", LogFmt("failed to open tmp: %s", tmp_path.c_str()));
      return false;
    }
    out << JsonToYaml(existing) << "\n";
    out.flush();
    if (!out.good()) {
      LOG_ERROR("event_store", LogFmt("write failed: %s", tmp_path.c_str()));
      return false;
    }
  }

  if (rename(tmp_path.c_str(), file_path.c_str()) != 0) {
    LOG_ERROR("event_store", LogFmt("rename failed: %s -> %s",
              tmp_path.c_str(), file_path.c_str()));
    return false;
  }

  return true;
}
