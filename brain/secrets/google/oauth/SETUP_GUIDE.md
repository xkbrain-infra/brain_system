# Google Drive MCP OAuth 配置指南

## 步骤 1: 创建 Google Cloud 项目

1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建新项目或选择现有项目
3. 项目名称建议: `brain-system-gdrive`

## 步骤 2: 启用 Google Drive API

1. 在 Google Cloud Console，进入 "APIs & Services" > "Library"
2. 搜索 "Google Drive API"
3. 点击 "Enable" 启用 API
4. 同样启用以下 API（可选，用于完整功能）:
   - Google Docs API
   - Google Sheets API
   - Google Slides API

## 步骤 3: 创建 OAuth 2.0 客户端凭据

1. 进入 "APIs & Services" > "Credentials"
2. 点击 "Create Credentials" > "OAuth client ID"
3. 如果提示配置 OAuth consent screen:
   - User Type: External（或 Internal 如果是 Workspace）
   - App name: Brain System Google Drive
   - User support email: 你的邮箱
   - Developer contact: 你的邮箱
   - Scopes: 暂时跳过
   - Test users: 添加你的 Google 账号
4. 回到 "Create OAuth client ID":
   - Application type: **Desktop app**（重要！）
   - Name: `brain-system-desktop-client`
5. 点击 "Create"
6. 下载 JSON 文件（点击下载图标）

## 步骤 4: 安装凭据文件

将下载的 JSON 文件重命名并移动到：
```bash
/brain/secrets/google_oauth/credentials.json
```

设置文件权限：
```bash
chmod 600 /brain/secrets/google_oauth/credentials.json
```

## 步骤 5: 执行 OAuth 授权流程

执行以下命令（DevOps 将协助）：
```bash
cd /brain/secrets/google_oauth
npx -y aegaea-drive-mcp auth
```

这将：
1. 打开浏览器窗口
2. 要求你登录 Google 账号
3. 授予权限访问 Google Drive
4. 生成 `token.json` 文件

## 步骤 6: 验证配置

确认以下文件已创建：
```
/brain/secrets/google_oauth/
├── credentials.json  (OAuth 客户端凭据)
├── token.json        (用户授权令牌)
└── SETUP_GUIDE.md    (本指南)
```

## 常见问题

### Q: 如果授权失败怎么办？
A: 删除 `token.json` 并重新执行步骤 5

### Q: 如何撤销访问权限？
A: 访问 https://myaccount.google.com/permissions 并撤销 "Brain System Google Drive" 应用

### Q: token.json 会过期吗？
A: 会。过期后 MCP 服务器会自动刷新令牌（使用 credentials.json）

### Q: 这些文件安全吗？
A:
- credentials.json: 敏感，权限 600，不提交 git
- token.json: 敏感，权限 600，不提交 git
- 定期备份并轮换

## 下一步

完成后通知 DevOps 继续部署步骤。
