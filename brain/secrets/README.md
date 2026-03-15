# Brain Global Secrets

**⚠️ 安全警告**：此目录包含敏感配置，请勿提交实际密钥到 git。

## 目录结构

```
/brain/secrets/
├── index.yaml              # 历史索引（不再作为 loader 入口）
├── .gitignore              # 防止敏感文件提交
├── README.md               # 本文件
├── google_oauth/           # Google OAuth 凭据
│   ├── credentials.json    (敏感，不提交)
│   ├── token.json          (敏感，不提交)
│   └── SETUP_GUIDE.md
├── telegram/               # Telegram 配置（按需创建）
├── futu/                   # 富途证券配置（按需创建）
├── database/               # 数据库凭证（按需创建）
├── firebase/               # Firebase 配置（按需创建）
└── agents/                 # Agent 专用配置（按需创建）
```

正式且唯一的 source registry 位于 `/brain/infrastructure/config/runtime_env/index.yaml`。

## 配置加载流程

### 启动时自动加载

系统启动时（agentctl），会自动调用配置加载器：

```bash
/brain/infrastructure/launch/loader_env_vars.py --reload --quiet
```

这会：
1. 读取 `/brain/infrastructure/config/runtime_env/index.yaml`
2. 按索引扫描 `/brain/secrets/` 下的 `.env` 文件
3. 合并环境变量到 `/xkagent_infra/runtime/config/.env`
4. 生成配置来源追溯文件

### 手动重新加载

配置更新后，手动重新加载：

```bash
/brain/infrastructure/launch/loader_env_vars.py --reload
```

## 添加新配置

### 1. 添加新分类

```bash
# 1. 创建分类目录
mkdir -p /brain/secrets/{category}
chmod 700 /brain/secrets/{category}

# 2. 更新 /brain/infrastructure/config/runtime_env/index.yaml 添加分类定义

# 3. 添加配置文件
vim /brain/secrets/{category}/config.env
chmod 600 /brain/secrets/{category}/config.env

# 4. 重新加载配置
/brain/infrastructure/launch/loader_env_vars.py --reload

# 5. 验证
cat /xkagent_infra/runtime/config/.env | grep {VAR_NAME}
```

### 2. 环境变量文件格式

```env
# /brain/secrets/{category}/{name}.env
# 示例

# Telegram Bot Token
TELEGRAM_BOT_TOKEN=110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
TELEGRAM_API_ID=12345
TELEGRAM_API_HASH=abc123def456

# 支持注释和空行
# 值可以用引号（会被自动去除）
SOME_VAR="value with spaces"
```

## 安全规范

### 文件权限

```bash
# 目录权限
chmod 700 /brain/secrets
chmod 700 /brain/secrets/{category}

# 敏感文件权限
chmod 600 /brain/secrets/{category}/*.env
chmod 600 /brain/secrets/{category}/*.pem
chmod 600 /brain/secrets/{category}/*.json

# 索引和文档可读
chmod 644 /brain/infrastructure/config/runtime_env/index.yaml
chmod 644 /brain/secrets/README.md
```

### Git 管理

**提交到 git**：
- `/brain/infrastructure/config/runtime_env/index.yaml` - 配置源索引
- `.gitignore` - 忽略规则
- `README.md` - 使用文档
- `**/SETUP_GUIDE.md` - 设置指南
- `**/*.template` - 模板文件
- `**/*.example` - 示例文件

**不提交到 git**（`.gitignore` 已配置）：
- `*.env` - 环境变量文件
- `*.pem`, `*.key` - 私钥文件
- `*.json` - JSON 配置（可能包含密钥）
- `*.secret` - 其他敏感文件

### 备份

**备份策略**：
- 频率: 每周一次
- 位置: 加密备份存储
- 包含: 所有文件（包括敏感文件）

**恢复**：
```bash
# 从备份恢复
rsync -av /backup/brain-secrets/ /brain/secrets/

# 设置权限
chmod 700 /brain/secrets
chmod 700 /brain/secrets/*
chmod 600 /brain/secrets/*/*.{env,pem,key,json}

# 重新加载配置
/brain/infrastructure/launch/loader_env_vars.py --reload
```

## 调试和验证

### 检查运行时配置

```bash
# 查看生成的环境变量
cat /xkagent_infra/runtime/config/.env

# 查看配置来源
cat /xkagent_infra/runtime/config/sources.yaml

# 查看加载时间
cat /xkagent_infra/runtime/config/loaded_at.txt

# 查看审计日志
tail /xkagent_infra/runtime/logs/config_audit.jsonl
```

### 验证配置完整性

```bash
/brain/infrastructure/launch/loader_env_vars.py --validate
```

### 检查权限

```bash
find /brain/secrets -type f -exec ls -l {} \; | grep -v '600\|644'
```

## 参考文档

- 配置管理规范: `/brain/base/spec/policies/config_management.yaml`
- Secrets 管理规范: `/brain/base/spec/policies/secrets_management.yaml`
- 架构文档: `/brain/base/spec/core/architecture.yaml`

## 常见问题

### Q: 如何添加新的环境变量？

A: 编辑对应分类的 `.env` 文件，然后重新加载配置。

### Q: 运行时配置丢失怎么办？

A: 运行时配置是临时的，可以重建：
```bash
/brain/infrastructure/launch/loader_env_vars.py --reload
```

### Q: 如何撤销某个密钥？

A: 从源文件删除，重新加载配置，并重启受影响的服务。

### Q: 配置加载失败怎么办？

A: 检查审计日志查看错误原因：
```bash
tail -1 /xkagent_infra/runtime/logs/config_audit.jsonl | jq .
```

## 下一步

完成配置后：
1. 验证配置加载: `loader_env_vars.py --validate`
2. 重启系统或受影响的服务
3. 检查服务日志确认配置生效
