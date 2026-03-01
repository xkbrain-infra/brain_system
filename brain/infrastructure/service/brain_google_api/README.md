# brain-google-api

Google API MCP Server for Agent Brain.

## 功能

- **Gmail**: 邮件读取、发送、搜索、管理
- **Drive**: 文件列表、上传、下载、删除
- **Calendar**: 日历事件创建、查询、删除

## 架构

```
brain-google-api/
├── src/              # 分层源码
│   ├── app/          # 进程入口
│   ├── core/         # 配置与日志
│   ├── domain/       # ACL / 账户领域逻辑
│   ├── infra/        # 外部适配 (Google API / IPC / OAuth2)
│   │   └── google/   # Google API 分模块实现 (gmail/drive/calendar/...)
│   ├── protocol/     # MCP 协议编解码
│   └── shared/       # 通用组件 (base64/crypto)
├── config/
│   ├── acl.json      # ACL 规则
│   └── resources.json # 资源配置
├── build/            # 编译产物
└── releases/         # 发布版本
```

## ACL 配置

`config/acl.json` 定义 agent 访问权限:

```json
{
  "rules": [
    {
      "agent_id": "agent_system_dev",
      "account_id": "*",
      "api_scope": "drive",
      "resource_tag": "*",
      "permission": "write"
    }
  ]
}
```

字段说明:
- `agent_id`: Agent 名称，`*` 表示所有 agent
- `account_id`: 账户 ID，`*` 表示所有账户
- `api_scope`: API 范围 (`gmail`, `drive`, `calendar`)
- `resource_tag`: 资源标签 (`inbox`, `send`, `events`, `*`)
- `permission`: 权限 (`read`, `write`, `admin`)

## 编译

```bash
cd /brain/infrastructure/service/brain-google-api
make
```

## 配置

配置文件位置:
- ACL: `/brain/infrastructure/service/brain-google-api/config/acl.json`
- 密钥: `/brain/secrets/brain-google-api/`

## MCP Tool

统一入口: `google_api`

参数:
```json
{
  "action": "gmail_list_messages|gmail_send_message|drive_list_files|calendar_create_event|...",
  "account_id": "account-001",
  "agent_id": "agent_system_dev",
  "resource_tag": "inbox"
}
```
