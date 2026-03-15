# 文档数据库 (agent_vectordb) 使用指南

## 概述

agent_vectordb 是基于 PostgreSQL + pgvector 的文档索引系统，为 Brain base/ 层所有 registry 文档提供 4 种查询能力。

## 架构

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  MCP Client │────→│  agent-vectordb  │────→│  system-graph-db │
│  (Agent)    │     │  (MCP Server)    │     │  PostgreSQL 16   │
└─────────────┘     │  stdio 协议       │     │  + pgvector 0.8  │
                    └──────┬───────────┘     │  brain_docs DB   │
                           │                 └──────────────────┘
                           │ embedding
                           ▼
                    ┌──────────────────┐
                    │  lml-embedding   │
                    │  bge-m3 (1024d)  │
                    │  :8001           │
                    └──────────────────┘
```

## MCP Tools

| Tool | 功能 | 参数 |
|------|------|------|
| `doc_query` | 关键词/domain/category/tags 组合查询 | keyword, domain, category, tags, limit |
| `doc_get` | 精确 ID 查找 | doc_id (required) |
| `doc_related` | 向量相似度关联推荐 | doc_id (required), limit |
| `doc_search` | 语义搜索（自然语言） | query (required), limit |

## 使用示例

### 关键词查询
```
doc_query(keyword="ipc")           → IPC 相关文档
doc_query(domain="knlg")           → 所有 knowledge 域文档
doc_query(category="TROUBLESHOOT") → 所有故障排查文档
doc_query(tags=["lep", "gate"])    → LEP gate 文档
```

### 精确查找
```
doc_get(doc_id="G-SPEC-CORE-LAYERS")  → 架构层级定义
```

### 关联推荐
```
doc_related(doc_id="G-SPEC-CORE-LAYERS", limit=5)  → 类似架构文档
```

### 语义搜索
```
doc_search(query="如何排查 IPC 超时")  → IPC Troubleshooting SOP (首位)
doc_search(query="Agent 创建流程")     → 相关规范文档
```

## 数据来源

4 个 registry.yaml 文件：
- `/brain/base/spec/registry.yaml` (69 文档)
- `/brain/base/workflow/registry.yaml` (4 文档)
- `/brain/base/knowledge/registry.yaml` (16 文档)
- `/brain/base/evolution/registry.yaml` (2 文档)

## 数据同步

新增/修改文档后，重新运行导入脚本：

```bash
cd /brain/infrastructure/service/agent_vectordb
python3 -m scripts.import_docs
```

该脚本使用 `merge` 语义，支持幂等重复执行。

## 连接配置

| 参数 | 默认值 |
|------|--------|
| DATABASE_URL | `postgresql+asyncpg://postgres:postgres@system-graph-db:5432/brain_docs` |
| EMBEDDING_URL | `http://lml-embedding:8001/v1/embeddings` |
| EMBEDDING_MODEL | `bge-m3` |

## 网络依赖

agent-core 容器需加入以下 Docker 网络：
- `system-graph-net` — 访问 PostgreSQL
- `lml-cs-assistant` — 访问 embedding 服务

## 代码位置

`/brain/infrastructure/service/agent_vectordb/`
