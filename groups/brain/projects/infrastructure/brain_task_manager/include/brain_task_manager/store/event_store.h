#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <mutex>

// EventStore: append-only 事件历史持久化
// 每个 project 独立文件：{data_dir}/{group}/{project_id}/events.json
// 文件格式：{"events": [...]}，按时间顺序追加，不在内存中保留全量
class EventStore {
public:
  explicit EventStore(const std::string& data_dir);

  // 追加一条事件到对应 project 的 events.json
  // 若文件/目录不存在则自动创建
  bool Append(const TaskEvent& event);

private:
  std::string EventFilePath(const std::string& group, const std::string& project_id) const;

  std::string data_dir_;
  mutable std::mutex mu_;
};
