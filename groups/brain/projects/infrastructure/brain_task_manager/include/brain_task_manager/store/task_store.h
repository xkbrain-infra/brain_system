#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/engine/fsm_engine.h"
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>
#include <optional>

struct TaskQueryFilter {
  std::string task_id;
  std::string project_id;
  std::string status;
  std::string group;
  std::string owner;
};

struct TaskStats {
  std::string project_id;
  int total = 0;
  std::unordered_map<std::string, int> by_status;
  std::unordered_map<std::string, int> by_priority;
};

struct PipelineCheckResult {
  bool valid = true;
  int total_tasks  = 0;
  int edges        = 0;
  int ready_tasks  = 0;
  int blocked_tasks = 0;
  bool cycle_detected = false;
  std::vector<std::string> cycle_path;
  std::vector<std::string> missing_dependencies;
  std::vector<std::string> flow_violations;
};

class TaskStore {
public:
  TaskStore(const std::string& data_dir, const FSMEngine& fsm);

  // 扫描 data_dir 下所有 {group}/{project_id}/tasks.json 加载入内存。
  // 返回加载的 task 数量。
  int Load();

  // 将内存中所有 task 按 (group, project_id) 分组，写回各自 tasks.json。
  // 返回成功写入的 project 数量。
  int Save();

  // 创建新任务。返回空字符串表示成功，否则为错误信息。
  std::string Create(const Task& task);

  // 更新任务字段，status 变更经 FSM 验证。
  // expected_version >= 0 时执行 CAS 检查。返回空字符串表示成功。
  std::string Update(const std::string& task_id, const json& fields,
                     int64_t expected_version = -1);

  // 按过滤条件查询任务（AND 组合）。
  std::vector<Task> Query(const TaskQueryFilter& filter) const;

  // 按 task_id 获取单个任务。不存在返回 nullopt。
  std::optional<Task> Get(const std::string& task_id) const;

  // 逻辑删除（active=false）。返回空字符串表示成功。
  std::string Delete(const std::string& task_id);

  // 统计指定 project 的任务数量分布。
  TaskStats Stats(const std::string& project_id) const;

  // 检查指定 project 的依赖 DAG 合法性。
  PipelineCheckResult PipelineCheck(const std::string& project_id) const;

  // 返回所有活跃任务（供 scheduler 扫描）。
  std::vector<Task> GetAll() const;

  int Count() const;

private:
  bool SaveProject(const std::string& group, const std::string& project_id);
  bool MatchesFilter(const Task& t, const TaskQueryFilter& f) const;
  void ScanDir(const std::string& dir, int depth);

  std::string data_dir_;
  const FSMEngine& fsm_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, Task> tasks_;  // task_id → Task（内存扁平索引）
};
