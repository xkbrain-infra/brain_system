# agent_abilities 构建系统使用指南

> 规范依据：`G-SPEC-STANDARD-AGENT-ABILITIES-BUILD`
> 构建根目录：`/brain/infrastructure/service/agent_abilities/`

## 目录结构速查

```
agent_abilities/
  src/            ← 唯一真源
    base/         ← 镜像 /brain/base/（spec/workflow/knowledge 等）
    hooks/        ← hooks Python 源码
    mcp/          ← MCP C 源码
    tests/        ← 所有测试（base/spec/ + hooks/）
  build/          ← 构建工具链（build.sh 入口）
  bin/            ← 编译产物（current 符号链接 = 构建成功标志）
  releases/       ← 历史版本快照
```

## 标准流水线

每次修改 src/ 后按顺序执行：

```bash
# 1. 查看 base ↔ src 差异
bash build/build.sh diff

# 2. 将 base 最新内容同步到 src
bash build/build.sh merge

# 3. 编译（src → bin/）
bash build/build.sh build <target>

# 4. 部署（bin/ → releases/ → /brain/base/）
bash build/build.sh deploy <target>

# 5. 生成覆盖统计（按需）
bash build/build.sh stats
```

## 构建目标

| Target     | 说明                          | 产物位置                     |
|------------|-----------------------------|-----------------------------|
| spec       | spec 文档编译 + 部署            | /brain/base/spec/           |
| hooks      | hooks 可执行文件编译             | bin/hooks/current/          |
| mcp_server | MCP C 服务编译                 | bin/mcp/                    |
| index      | index.yaml 生成 + 部署         | /brain/base/index.yaml      |
| stats      | spec/lep/hooks 覆盖统计生成     | knowledge/brian_system/spec/ |

## 构建门控（build gate）

`bin/{target}/current` 符号链接是构建成功的唯一标志：

- build 开始 → **删除** `current`
- build 成功 → **重建** `current` 指向最新版本
- deploy 前 → **检查** `current` 存在，不存在则拒绝部署

```bash
# 手动检查 hooks 是否已成功构建
ls -la bin/hooks/current
```

## stats 输出格式

`build stats` 同时生成两个文件（内容一致）：

| 文件                                | 用途             |
|-------------------------------------|-----------------|
| `knowledge/brian_system/spec/spec_stats.yaml` | 机器可读，构建流水线消费 |
| `knowledge/brian_system/spec/spec_stats.md`   | 人/LLM 阅读，上下文加载 |

### 表格列命名规范

所有统计表格统一使用 `Rule` 列（禁止用 title / name / 标题 / 说明）：

| 表格        | 列                                    | Rule 取值来源            |
|-------------|---------------------------------------|------------------------|
| Spec 文档   | ID \| Rule \| 路径                    | spec registry description 字段 |
| LEP Gates   | Gate ID \| Rule \| Universal \| 路径  | gate 文件 rule 字段首行  |
| Hooks 覆盖  | Gate ID \| Method \| Universal \| 路径 | —                      |

## 常用操作

### 完整重建并部署 spec

```bash
bash build/build.sh merge && \
bash build/build.sh build spec && \
bash build/build.sh deploy spec
```

### 只更新统计

```bash
bash build/build.sh stats
bash build/build.sh deploy knowledge   # 部署到 /brain/base/knowledge/
```

### 验证所有文档

```bash
bash build/build.sh validate all_docs
```

### 查看所有可用目标

```bash
bash build/build.sh help
```

## 常见问题

**Q: deploy 报错 "build failed or not yet run"**
A: `bin/{target}/current` 不存在，需先执行 `build` 再 `deploy`。

**Q: stats 生成后 /brain/base/knowledge 没更新**
A: stats 只写入 `src/base/knowledge/`，需执行 `deploy knowledge` 才会同步到 base。

**Q: 修改了 src/base/spec/ 后需要做什么**
A: `build spec → deploy spec`，不需要 merge（merge 是 base→src 方向）。
