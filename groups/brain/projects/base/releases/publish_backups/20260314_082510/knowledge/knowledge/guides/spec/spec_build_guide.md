# Spec 编译系统操作指南

## 概述

Spec 采用 **src → validate → test → publish** 的开发模式：

- **源码 (src)**：`/brain/infrastructure/service/agent_abilities/spec/src/`
- **发布目标**：`/brain/base/spec/`（所有 Agent 引用的稳定路径）
- **版本快照**：`/brain/infrastructure/service/agent_abilities/spec/releases/v*/`

所有 spec 修改必须在 `src/` 中进行，通过 `build.sh publish` 发布到 `base/spec/`。
**禁止直接修改 `base/spec/`**。

## 目录结构

```
/brain/infrastructure/service/agent_abilities/spec/
├── src/                    # 源码（在这里编辑）
│   ├── core/               # 核心规范 (lep.yaml, layers.yaml, workflow.yaml)
│   ├── policies/           # 执行政策 (8 子目录)
│   ├── standards/          # 技术标准
│   ├── templates/          # 模板
│   ├── registry.yaml       # 文档索引
│   └── index.yaml          # 结构索引
├── releases/               # 版本快照
│   ├── v2.0.0/             # 完整快照 + RELEASE.yaml
│   └── ...
├── scripts/
│   ├── build.sh            # 统一入口（validate/test/publish/rollback）
│   └── validate.py         # 校验脚本
├── tests/
│   ├── test_index_chain.py # 索引链完整性测试
│   └── test_role_coverage.py # 角色 spec 覆盖度测试
└── config/
    ├── build.yaml          # 编译配置
    └── version.yaml        # 版本号 + changelog
```

## 命令速查

```bash
S=/brain/infrastructure/service/agent_abilities/spec/scripts/build.sh

$S validate          # 校验 src/（registry/YAML/路径/孤立文件）
$S test              # 运行测试（索引链 + 角色覆盖）
$S diff              # 对比 src/ vs base/spec/
$S publish           # 校验 → 测试 → 快照 → 发布
$S publish --dry-run # 预览不实际发布
$S publish 2.1.0     # 指定版本号发布
$S versions          # 列出已发布版本
$S rollback 2.0.0    # 回滚到指定版本
```

## 发布流程

```
build.sh publish [VERSION]
  ├── Step 1: validate src/
  ├── Step 2: run tests (index chain + role coverage)
  ├── Step 3: diff src/ vs base/spec/
  ├── Step 4: snapshot → releases/v{VERSION}/
  └── Step 5: sync src/ → base/spec/ + post-validate
```

## 校验项 (validate.py)

| 检查 | 说明 |
|------|------|
| registry_paths_exist | registry 中所有 path 指向真实文件 |
| meta_document_count | meta.total_documents == 实际条目数 |
| category_counts | 各 category count == 列表长度 |
| quick_lookup_refs | quick_lookup 引用的 ID 在 documents 中存在 |
| yaml_syntax | 所有 .yaml 文件语法正确 |
| orphan_files | 无未注册的 policy/standard 文件 |

## 测试项

### test_index_chain.py — 索引链完整性

验证从 index.yaml 到实际文件的完整链条：
- index.yaml → registry.yaml 存在
- 每个 document ID 都在 categories 中
- quick_lookup 引用的 ID 都在 documents 中
- 所有 document path 指向真实文件
- core/lep.yaml universal_gates → lep/index.yaml → gate 文件

### test_role_coverage.py — 角色覆盖度

按角色验证 spec 是否覆盖了该角色所需的知识：
- 每个角色都有模板文件
- 每个角色在 quick_lookup 中有条目
- 每个角色的必需主题（must）在 quick_lookup 中可达
  - PMO: workflow, estimation, agent
  - Architect: architecture, layers, lep
  - Developer: lep, verification, workflow
  - QA: verification, workflow, lep
  - DevOps: docker, deployment, database
  - Frontdesk: ipc, agent
  - Researcher: workflow, lep
  - UI Designer: workflow, lep

## 新增文档的流程

1. 在 `src/` 对应目录下创建文件
2. 在 `src/registry.yaml` 中注册：
   - 添加 document 条目（ID、path、category、tags、load_triggers）
   - 更新 `meta.total_documents` 计数
   - 更新对应 category 的 count 和 documents 列表
   - 添加 quick_lookup 关键词映射
3. `build.sh validate` — 确认无错误
4. `build.sh test` — 确认索引链和角色覆盖
5. `build.sh publish` — 发布

## 版本管理

版本文件：`config/version.yaml`

- 结构性变更时手动更新 `version` 和 `changelog`
- `publish` 时自动更新 `last_build` 时间戳
- 每次 publish 在 `releases/v{VERSION}/` 创建完整快照

## 回滚

```bash
# 方式 1: 回滚到已发布版本
build.sh rollback 2.0.0

# 方式 2: git 回滚
git checkout -- base/spec/
```

## LEP 关联

- **G-GATE-SPEC-LOCATION** — spec 文件必须在指定目录
- **G-GATE-SPEC-SYNC** — spec 变更必须同步
- **G-GATE-NAWP** — 结构性修改需要 Plan + 批准
