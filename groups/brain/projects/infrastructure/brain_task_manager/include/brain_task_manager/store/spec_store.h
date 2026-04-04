#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>

struct ProjectQueryFilter {
  std::string project_id;
  std::string group;
  std::string stage;
};

// ProjectStore: 管理 ProjectRecord 的持久化
// 存储路径: {data_dir}/{group}/{project_id}/project.json
// 启动时扫描 data_dir 下所有 project.json 文件加载入内存
class ProjectStore {
public:
  explicit ProjectStore(const std::string& data_dir);

  // 扫描 data_dir 加载所有 project.json。返回加载数量。
  int Load();

  // 将所有 project 写回各自的 project.json。返回成功数量。
  int Save();

  // 创建新 project。返回首个 intake task_id；失败时 out_error 非空。
  std::string Create(const ProjectRecord& proj, std::string& out_error);

  // 将 project 推进到下一阶段（必须顺序推进）。
  std::string Progress(const std::string& project_id, const std::string& target_stage);

  // 查询 project 列表。
  std::vector<ProjectRecord> Query(const ProjectQueryFilter& filter) const;

  // 获取单个 project（不存在返回 nullptr）。
  const ProjectRecord* Get(const std::string& project_id) const;

  // 获取所有活跃 project 的 (group, project_id) 列表，供 TaskStore 扫描用。
  std::vector<std::pair<std::string, std::string>> ListProjectKeys() const;

  int Count() const;

private:
  bool SaveOne(const ProjectRecord& proj);
  bool MatchesFilter(const ProjectRecord& p, const ProjectQueryFilter& f) const;
  void ScanDir(const std::string& dir, int depth);

  std::string data_dir_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, ProjectRecord> projects_;  // project_id → record
};

// 向后兼容别名
using SpecStore       = ProjectStore;
using SpecQueryFilter = ProjectQueryFilter;
