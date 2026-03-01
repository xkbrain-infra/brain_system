# 文件组织规范使用示例

本文档提供具体的使用示例，帮助 Agent 理解和应用文件组织规范。

## 目录
- [基础用法](#基础用法)
- [实际场景](#实际场景)
- [Agent 集成](#agent-集成)
- [常见错误](#常见错误)

---

## 基础用法

### 使用 Python Helper

```python
from file_organization_helper import FileOrganizer, ensure_path

# 创建组织器实例
org = FileOrganizer()

# 场景 1: 创建日志文件
log_path = org.log_path("agent_system_pmo", "audit")
ensure_path(log_path)  # 创建所需目录
# 结果: /brain/runtime/logs/2026/02/13/agent_system_pmo_audit_2026-02-13.jsonl

# 场景 2: 创建项目报告
report_path = org.project_path(
    "org", "xkquant", "newsalpha", "reports", "incident_002.md"
)
ensure_path(report_path)
# 结果: /brain/groups/org/xkquant/projects/newsalpha/reports/incident_002.md

# 场景 3: 创建配置文件
config_path = org.config_path("mcp", "agent_frontdesk.mcp.json")
ensure_path(config_path)
# 结果: /brain/runtime/config/mcp/agent_frontdesk.mcp.json
```

### 直接构造路径（不使用 Helper）

```python
from pathlib import Path
from datetime import datetime

# Time-Based 模式
now = datetime.now()
log_path = Path(f"/brain/runtime/logs/{now.year:04d}/{now.month:02d}/{now.day:02d}/agent.log")

# Business-Based 模式
report_path = Path("/brain/groups/org/xkquant/projects/newsalpha/reports/incident.md")

# Type-Based 模式
config_path = Path("/brain/runtime/config/agents/agent_frontdesk.mcp.json")
```

---

## 实际场景

### 场景 1: PMO Agent 创建任务报告

**需求**: PMO 完成任务后需要生成完成报告。

**分析**:
- 文件类型: 输出产物
- 关联: 特定任务
- 选择模式: **business_based**

**实现**:

```python
# 方法 1: 使用 Helper
from file_organization_helper import organizer, ensure_path

report_path = organizer.task_path(
    org="org",
    group="brain_system",
    task_id="BS-TASK-005",
    category="reports",
    filename="completion_report.md"
)

ensure_path(report_path)
# 写入报告内容...

# 方法 2: 直接构造
from pathlib import Path

report_path = Path(
    "/brain/groups/org/brain_system/tasks/BS-TASK-005/reports/completion_report.md"
)
report_path.parent.mkdir(parents=True, exist_ok=True)
# 写入报告内容...
```

**结果路径**: `/brain/groups/org/brain_system/tasks/BS-TASK-005/reports/completion_report.md`

---

### 场景 2: DevOps Agent 记录部署日志

**需求**: 记录 cxx_service v3.1 的部署过程。

**分析**:
- 文件类型: 日志文件
- 关联: 时间序列
- 选择模式: **time_based**

**实现**:

```python
from file_organization_helper import organizer, ensure_path
from datetime import datetime

# 创建部署日志路径
deployment_log = organizer.time_based_path(
    base_dir="runtime/logs/deployments",
    filename="cxx_service_v3.1_deploy.log",
    template="daily"
)

ensure_path(deployment_log)

# 写入日志
with open(deployment_log, "a") as f:
    f.write(f"[{datetime.now()}] Starting deployment...\n")
```

**结果路径**: `/brain/runtime/logs/deployments/2026/02/13/cxx_service_v3.1_deploy.log`

---

### 场景 3: Architect Agent 生成 MCP 配置

**需求**: 为 frontdesk agent 生成 .mcp.json 配置文件。

**分析**:
- 文件类型: 配置文件
- 关联: 系统配置，非项目特定
- 选择模式: **type_based**

**实现**:

```python
from file_organization_helper import organizer, ensure_path
import json

# 生成配置文件路径
config_path = organizer.config_path(
    subsystem="mcp",
    filename="agent_system_frontdesk.mcp.json"
)

ensure_path(config_path)

# 写入配置
config = {
    "mcpServers": {
        "brain-ipc-c": {
            "command": "python",
            "args": ["/brain/infrastructure/service/agent_abilities/mcp/brain_ipc_c/bin/current/brain_ipc_c_mcp_server"]
        }
    }
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
```

**结果路径**: `/brain/runtime/config/mcp/agent_system_frontdesk.mcp.json`

---

### 场景 4: Researcher Agent 生成日报

**需求**: XKQuant 组的 researcher 每天生成日报，需要按时间组织。

**分析**:
- 文件类型: 输出产物
- 关联: 特定项目 + 时间序列
- 选择模式: **组合模式 (business + time)**

**实现**:

```python
from file_organization_helper import organizer, ensure_path
from datetime import datetime

# 使用组合模式生成日报路径
daily_report = organizer.hybrid_project_time_path(
    org="org",
    group="xkquant",
    project_id="newsalpha",
    category="reports/daily",
    filename="daily_report.md"
)

ensure_path(daily_report)

# 写入日报内容
content = f"""# XKQuant NewsAlpha Daily Report
Date: {datetime.now().strftime('%Y-%m-%d')}

## Summary
...
"""

with open(daily_report, "w") as f:
    f.write(content)
```

**结果路径**: `/brain/groups/org/xkquant/projects/newsalpha/reports/daily/2026/02/13/daily_report.md`

---

### 场景 5: QA Agent 保存测试结果

**需求**: 保存 agent_orchestrator 项目的单元测试覆盖率报告。

**分析**:
- 文件类型: 测试输出
- 关联: 特定项目 + 测试类型
- 选择模式: **组合模式 (business + type)**

**实现**:

```python
from file_organization_helper import organizer, ensure_path

# 项目内按类型组织
test_report = organizer.project_path(
    org="org",
    group="brain_system",
    project_id="agent_orchestrator",
    category="tests/coverage",
    filename="unit_test_2026-02-13.html"
)

ensure_path(test_report)
# 保存覆盖率报告...
```

**结果路径**: `/brain/groups/org/brain_system/projects/agent_orchestrator/tests/coverage/unit_test_2026-02-13.html`

---

## Agent 集成

### 在 Agent CLAUDE.md 中声明默认模式

```markdown
# Agent 文件组织策略

## 默认组织模式
- 日志文件: time_based (runtime/logs/YYYY/MM/DD/)
- 项目产物: business_based (groups/org/{group}/projects/{project_id}/)
- 配置文件: type_based (runtime/config/{subsystem}/)

## 路径模板
### 审计日志
```python
runtime/logs/{YYYY}/{MM}/{DD}/agent_{agent_name}_audit_{YYYY-MM-DD}.jsonl
```

### 项目报告
```python
groups/org/{group}/projects/{project_id}/reports/{filename}
```
```

### 在 Agent 代码中集成

```python
import sys
sys.path.append("/brain/base/spec/standards")
from file_organization_helper import organizer, ensure_path

class MyAgent:
    def __init__(self, name: str, group: str):
        self.name = name
        self.group = group
        self.org = organizer

    def create_log(self, log_type: str = "general"):
        """创建日志文件"""
        log_path = self.org.log_path(self.name, log_type)
        ensure_path(log_path)
        return log_path

    def create_report(self, project_id: str, filename: str):
        """创建项目报告"""
        report_path = self.org.project_path(
            "org", self.group, project_id, "reports", filename
        )
        ensure_path(report_path)
        return report_path
```

---

## 常见错误

### ❌ 错误 1: 直接在顶级目录创建文件

```python
# 错误
Path("/brain/report.md")
Path("/brain/temp.log")

# 正确
organizer.project_path("org", "xkquant", "newsalpha", "reports", "report.md")
organizer.time_based_path("runtime/tmp", "temp.log")
```

### ❌ 错误 2: 使用无意义的目录名

```python
# 错误
Path("/brain/runtime/misc/output.txt")
Path("/brain/groups/org/xkquant/other/file.md")
Path("/brain/temp/test.log")

# 正确
organizer.type_based_path("build", "output.txt", "artifacts")
organizer.project_path("org", "xkquant", "newsalpha", "analysis", "file.md")
organizer.time_based_path("runtime/tmp", "test.log", template="compact")
```

### ❌ 错误 3: 路径过深

```python
# 错误（8 层）
Path("/brain/groups/org/xkquant/projects/newsalpha/reports/daily/2026/02/13/morning/early/file.md")

# 正确（6 层）
organizer.hybrid_project_time_path(
    "org", "xkquant", "newsalpha", "reports/daily", "file.md"
)
# 结果: /brain/groups/org/xkquant/projects/newsalpha/reports/daily/2026/02/13/file.md
```

### ❌ 错误 4: 时间格式不统一

```python
# 错误
Path("/brain/runtime/logs/2026-2-13/agent.log")  # 月日没补零
Path("/brain/runtime/logs/26/02/13/agent.log")  # 年份只有两位

# 正确
organizer.time_based_path("runtime/logs", "agent.log")  # 自动格式化为 2026/02/13
```

### ❌ 错误 5: 使用 /tmp 存储文件

```python
# 错误
Path("/tmp/agent_output.txt")  # 系统临时目录，重启后丢失

# 正确
organizer.time_based_path("runtime/tmp", "agent_output.txt", template="compact")
# 结果: /brain/runtime/tmp/2026-02-13/agent_output.txt
```

---

## 验证工具

### 路径验证

```python
from file_organization_helper import organizer

# 验证路径是否符合规范
path = Path("/brain/runtime/logs/2026/02/13/agent.log")
valid, message = organizer.validate_path(path)

if not valid:
    print(f"路径不合规: {message}")
else:
    print("路径符合规范")
```

### 自动修正

```python
def auto_fix_path(bad_path: str) -> Path:
    """尝试自动修正不合规的路径"""
    bad = Path(bad_path)

    # 如果是 /tmp 下的文件，迁移到 runtime/tmp
    if "/tmp/" in str(bad):
        filename = bad.name
        return organizer.time_based_path("runtime/tmp", filename, template="compact")

    # 如果是顶级文件，根据扩展名推断类型
    if bad.parent == Path("/brain"):
        if bad.suffix == ".log":
            return organizer.log_path("unknown", "general")
        elif bad.suffix in [".md", ".txt", ".pdf"]:
            return organizer.project_path("org", "brain_system", "misc", "documents", bad.name)

    return bad  # 无法自动修正
```

---

## 迁移检查清单

如果你发现现有文件不符合规范，使用以下清单进行迁移：

- [ ] 扫描顶级目录（`/brain/*.{md,txt,log,json}`）
- [ ] 识别文件类型和用途
- [ ] 选择合适的组织模式
- [ ] 创建目标目录结构
- [ ] 移动文件到新位置
- [ ] 更新所有引用（配置、脚本、文档）
- [ ] 验证功能正常
- [ ] 删除旧文件

---

## 参考资料

- **完整规范**: `/brain/base/spec/standards/file_organization.yaml`
- **Helper 库**: `/brain/base/spec/standards/file_organization_helper.py`
- **LEP Gate**: `/brain/base/spec/core/lep.yaml` - G-FILE-ORG
- **索引注册**: `/brain/base/spec/standards/index.yaml`
