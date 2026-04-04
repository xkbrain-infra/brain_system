#include "brain_task_manager/store/spec_store.h"
#include "brain_task_manager/core/yaml_util.h"
#include <fstream>
#include <sys/stat.h>
#include <dirent.h>
#include <cerrno>

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

ProjectStore::ProjectStore(const std::string& data_dir) : data_dir_(data_dir) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
}

// 递归扫描 data_dir，找所有 project.json 文件
void ProjectStore::ScanDir(const std::string& dir, int depth) {
  if (depth > 6) return;  // 防止过深递归
  DIR* d = opendir(dir.c_str());
  if (!d) return;

  struct dirent* entry;
  while ((entry = readdir(d)) != nullptr) {
    if (entry->d_name[0] == '.') continue;
    std::string name = entry->d_name;
    std::string path = dir + name;

    struct stat st;
    if (stat(path.c_str(), &st) != 0) continue;

    if (S_ISDIR(st.st_mode)) {
      ScanDir(path + "/", depth + 1);
    } else if (name == "project.yaml") {
      std::ifstream f(path);
      if (!f.is_open()) continue;
      YAML::Node node = YAML::Load(f);
      json j = YamlToJson(node);
      if (j.is_null()) {
        LOG_ERROR("project_store", LogFmt("failed to parse: %s", path.c_str()));
        continue;
      }
      ProjectRecord p = ProjectRecord::from_json(j);
      if (!p.project_id.empty()) {
        projects_[p.project_id] = p;
      }
    }
  }
  closedir(d);
}

int ProjectStore::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  projects_.clear();
  ScanDir(data_dir_, 0);
  LOG_INFO("project_store", LogFmt("loaded %d projects from %s",
           (int)projects_.size(), data_dir_.c_str()));
  return static_cast<int>(projects_.size());
}

bool ProjectStore::SaveOne(const ProjectRecord& proj) {
  std::string dir = ProjectDataDir(data_dir_, proj.group, proj.project_id);
  if (!MkdirP(dir)) {
    LOG_ERROR("project_store", LogFmt("failed to create dir: %s", dir.c_str()));
    return false;
  }
  std::string file_path = dir + "project.yaml";
  std::string tmp_path  = file_path + ".tmp";

  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) return false;
    out << JsonToYaml(proj.to_json()) << "\n";
    out.flush();
    if (!out.good()) return false;
  }

  return rename(tmp_path.c_str(), file_path.c_str()) == 0;
}

int ProjectStore::Save() {
  std::lock_guard<std::mutex> lock(mu_);
  int ok = 0;
  for (auto& [id, proj] : projects_) {
    if (SaveOne(proj)) ok++;
    else LOG_ERROR("project_store", LogFmt("failed to save project: %s", id.c_str()));
  }
  return ok;
}

std::string ProjectStore::Create(const ProjectRecord& proj, std::string& out_error) {
  std::lock_guard<std::mutex> lock(mu_);

  if (proj.project_id.empty()) { out_error = "project_id is required"; return ""; }
  if (proj.title.empty())      { out_error = "title is required";      return ""; }
  if (proj.group.empty())      { out_error = "group is required";      return ""; }
  if (proj.owner.empty())      { out_error = "owner is required";      return ""; }

  if (projects_.count(proj.project_id)) {
    out_error = "project_id already exists: " + proj.project_id;
    return "";
  }

  ProjectRecord p = proj;
  p.stage = SpecStage::S1_alignment;
  p.active = true;
  if (p.created_at.empty()) p.created_at = NowUTC();
  p.updated_at = p.created_at;

  if (!SaveOne(p)) {
    out_error = "failed to persist project: " + p.project_id;
    return "";
  }

  projects_[p.project_id] = p;

  std::string intake_task_id = p.project_id + "-T001";
  out_error = "";
  return intake_task_id;
}

std::string ProjectStore::Progress(const std::string& project_id,
                                    const std::string& target_stage) {
  std::lock_guard<std::mutex> lock(mu_);

  auto it = projects_.find(project_id);
  if (it == projects_.end()) return "project not found: " + project_id;
  if (!it->second.active)    return "project is archived: " + project_id;
  if (!IsValidStage(target_stage)) return "invalid stage: " + target_stage;

  ProjectRecord& p = it->second;
  SpecStage target = SpecStageFromStr(target_stage);
  int current_order = SpecStageOrder(p.stage);
  int target_order  = SpecStageOrder(target);

  if (target_order != current_order + 1) {
    return "illegal stage progression: " + std::string(SpecStageToStr(p.stage))
           + " -> " + target_stage + " (must advance sequentially)";
  }

  p.stage      = target;
  p.updated_at = NowUTC();
  if (target == SpecStage::Archived) p.active = false;

  if (!SaveOne(p)) return "failed to persist project after progress: " + project_id;
  return "";
}

std::vector<ProjectRecord> ProjectStore::Query(const ProjectQueryFilter& filter) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<ProjectRecord> result;
  for (auto& [id, p] : projects_) {
    if (!p.active && filter.project_id.empty()) continue;
    if (MatchesFilter(p, filter)) result.push_back(p);
  }
  return result;
}

const ProjectRecord* ProjectStore::Get(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = projects_.find(project_id);
  if (it == projects_.end()) return nullptr;
  return &it->second;
}

std::vector<std::pair<std::string, std::string>> ProjectStore::ListProjectKeys() const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<std::pair<std::string, std::string>> result;
  for (auto& [id, p] : projects_) {
    result.emplace_back(p.group, p.project_id);
  }
  return result;
}

int ProjectStore::Count() const {
  std::lock_guard<std::mutex> lock(mu_);
  int count = 0;
  for (auto& [id, p] : projects_) {
    if (p.active) count++;
  }
  return count;
}

bool ProjectStore::MatchesFilter(const ProjectRecord& p, const ProjectQueryFilter& f) const {
  if (!f.project_id.empty() && p.project_id != f.project_id) return false;
  if (!f.group.empty()      && p.group      != f.group)       return false;
  if (!f.stage.empty()      && SpecStageToStr(p.stage) != f.stage) return false;
  return true;
}
