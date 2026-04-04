---
id: G-SKILL-VALIDATE-ALIGNMENT
name: validate-alignment
description: "验证 Brain spec 与实际代码的一致性。在接手项目、重构后、或定期健康检查时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, Read, Glob, Grep
argument-hint: "<group> <project> [--check all|paths|imports|dockerfile]"
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/validate-alignment
  version: "1.0.0"
---

# validate-alignment — Brain-App 对齐验证

检测 Brain spec 文档与实际代码之间的不一致，输出带修复建议的验证报告。

## 何时使用

| 场景 | 说明 |
|------|------|
| 接手已有项目 | 确认文档与代码是否同步 |
| 代码重构后 | 确认 spec 已同步更新 |
| 定期健康检查 | agent-brain_manager 定期触发 |
| 发现文档与代码矛盾时 | 快速定位差异 |

## 六项检查

| ID | 检查项 | 严重性 |
|----|--------|--------|
| VAL-001 | Brain 层不含代码文件（.py/.js/.go） | CRITICAL |
| VAL-002 | projects.yaml 中的路径与实际目录一致 | CRITICAL |
| VAL-003 | 代码目录命名符合语言规范（Python→src/） | WARNING |
| VAL-004 | tech_solution.md 描述与实际目录结构匹配 | HIGH |
| VAL-005 | 导入语句与目录命名一致（不混用 src/source） | HIGH |
| VAL-006 | Dockerfile PYTHONPATH 与代码目录一致 | HIGH |

## 执行方式

```bash
# 验证单个项目
python3 /xkagent_infra/brain/base/skill/validate-alignment/src/run.py \
  --group brain \
  --project my_project

# 输出示例
# VAL-001 PASS  Brain 层无代码文件
# VAL-002 PASS  projects.yaml 路径正确
# VAL-003 WARN  目录使用 source/ 而非 src/
# VAL-004 HIGH  tech_solution.md 未描述实际目录结构
# VAL-005 HIGH  found 12 'from source.' imports，但目录是 src/
# VAL-006 PASS  Dockerfile PYTHONPATH 正确
#
# 总体状态: WARNING
# 报告: memory/validation_report_20260322.md
```

## 发现问题后的处理

**VAL-003/VAL-005（目录命名不一致）**：
```bash
mv source src
find . -name "*.py" -exec sed -i 's/from source\./from src./g' {} \;
```

**VAL-004（spec 与代码不符）**：优先更新 spec（代码是现实），除非代码明显偏离设计意图。

**VAL-006（Dockerfile PYTHONPATH 错误）**：
```dockerfile
ENV PYTHONPATH=/app/domain/{project}:/app/domain/{project}/src
```

## 输出报告

报告写入 `memory/validation_report_{timestamp}.md`，包含：
- 各检查项的 PASS/WARNING/FAIL 状态
- 具体问题描述
- 逐步修复命令
- 总体对齐度评分
