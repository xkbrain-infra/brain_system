# Notion MCP Server

Notion MCP Server for Claude Code - 提供 Notion 数据库查询、页面创建、全文搜索等功能。

## 配置步骤

### 1. 创建 Notion Integration

1. 访问 [Notion Integrations](https://www.notion.so/my-integrations)
2. 点击 **+ New integration**
3. 填写名称（如 `Claude Code Agent`）
4. 选择关联的 Workspace
5. 点击 **Submit**
6. 复制生成的 **Internal Integration Token**（以 `secret_` 开头）

### 2. 配置 Token

```bash
# 复制示例文件
cp /brain/secrets/notion/token.example /brain/secrets/notion/token

# 编辑 token 文件，替换为你的实际 token
vi /brain/secrets/notion/token
```

**重要**：token 文件格式应该是纯文本，只包含 token 本身（以 `secret_` 开头），不要包含任何额外字符。

### 3. 授权数据库访问

1. 打开你想让 Claude Code 访问的 Notion 数据库
2. 点击右上角 **···** → **Connections**
3. 选择你创建的 Integration（如 `Claude Code Agent`）
4. 点击 **Allow connection**

### 4. 重启 Agent

配置完成后，重启 Agent 以加载新的 MCP Server：

```bash
# 在 agent 的 tmux session 中
agentctl restart agent_foo_qwen
```

## 使用的工具

### 1. notion-search
全文搜索 Notion 工作区的页面和数据库。

```json
{
  "query": "项目进度"
}
```

### 2. notion-query-database
查询特定数据库。

```json
{
  "database_id": "your-database-id-here",
  "filter": {
    "property": "Status",
    "select": { "equals": "In Progress" }
  },
  "sorts": [
    { "property": "Created", "direction": "descending" }
  ]
}
```

### 3. notion-create-page
创建新页面。

```json
{
  "parent": { "database_id": "your-database-id" },
  "properties": {
    "Name": { "title": [{ "text": { "content": "新任务" } }] }
  },
  "children": []
}
```

## 获取 Database ID

1. 打开数据库页面
2. 点击右上角 **···** → **Copy link**
3. Database ID 是 URL 中 `/` 和 `?` 之间的部分，格式如：
   ```
   https://www.notion.so/workspace/8a9b7c6d5e4f3a2b1c0d9e8f7a6b5c4d?v=...
   ```
   其中 `8a9b7c6d5e4f3a2b1c0d9e8f7a6b5c4d` 就是 Database ID

## 故障排查

### Token 无效
- 检查 token 是否以 `secret_` 开头
- 确认 token 文件没有额外的空格或换行符
- 确认 Integration 已授权访问数据库

### 无法连接数据库
- 确认数据库已通过 **Connections** 授予 Integration 访问权限
- 检查 Database ID 是否正确

### 启动失败
- 检查 `/brain/infrastructure/mcp/notion/node_modules` 是否存在
- 运行 `cd /brain/infrastructure/mcp/notion && npm install` 重新安装依赖

## 支持的操作

- ✅ 搜索页面和数据库
- ✅ 查询数据库（支持过滤和排序）
- ✅ 创建新页面
- ⏳ 更新页面（待实现）
- ⏳ 删除页面（待实现）
