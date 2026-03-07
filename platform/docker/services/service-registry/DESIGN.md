# 服务注册中心设计方案

## 设计原则

1. **渐进式演进**：基于现有 IPC 架构扩展，不引入重型外部依赖
2. **容器化优先**：所有组件必须支持 Docker 部署
3. **可测试性**：提供完整的测试覆盖和本地开发环境
4. **向后兼容**：不影响现有 Agent 和服务的运行

## 技术选型

### 方案对比

| 维度 | 方案 A: 扩展 IPC | 方案 B: 独立服务 |
|------|-----------------|-----------------|
| 实现复杂度 | 中（需修改现有服务）| 低（独立部署）|
| 资源占用 | 低（共享 IPC 进程）| 中（独立容器）|
| 可用性 | 与 IPC 绑定 | 可独立伸缩 |
| 测试难度 | 高（耦合现有代码）| 低（完全独立）|
| 维护成本 | 中 | 低 |

**推荐：方案 B（独立服务）**

理由：
- 完全隔离，不影响现有系统
- 测试和部署独立
- 可单独升级和扩展
- 符合微服务设计理念

## 架构设计

```
┌──────────────────────────────────────────────────────────────┐
│                    service-registry                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │ Registry    │  │ Health      │  │ Watch/Notify        │   │
│  │ API (HTTP)  │  │ Checker     │  │ (WebSocket/SSE)     │   │
│  └─────────────┘  └─────────────┘  └─────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              存储层 (Pluggable)                        │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐               │   │
│  │  │ Memory  │  │ SQLite  │  │ Redis   │               │   │
│  │  │ (dev)   │  │ (default)│  │ (prod)  │               │   │
│  │  └─────────┘  └─────────┘  └─────────┘               │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Services     │    │    Agents     │    │    Clients    │
│  (Gateway,    │    │  (Manager,    │    │  (CLI,        │
│   Task Mgr)   │    │   DevOps)     │    │   Dashboard)  │
└───────────────┘    └───────────────┘    └───────────────┘
```

## 核心功能

### 1. 服务注册 (Register)

```yaml
POST /api/v1/registry/services
Content-Type: application/json

{
  "service_id": "brain-gateway-01",
  "service_name": "brain_gateway",
  "service_type": "http",
  "version": "1.2.0",
  "endpoints": [
    {
      "protocol": "http",
      "host": "10.0.0.5",
      "port": 8080,
      "path": "/api/v1"
    }
  ],
  "metadata": {
    "group": "brain",
    "region": "local",
    "weight": 100
  },
  "health_check": {
    "type": "http",
    "endpoint": "/health",
    "interval": 30,
    "timeout": 5
  },
  "ttl": 60  # 秒，0表示永久
}
```

### 2. 服务发现 (Discover)

```yaml
GET /api/v1/registry/services?name=brain_gateway&healthy=true

Response:
{
  "services": [
    {
      "service_id": "brain-gateway-01",
      "service_name": "brain_gateway",
      "status": "healthy",
      "endpoints": [...],
      "last_seen": "2026-03-07T12:00:00Z"
    }
  ]
}
```

### 3. 健康检查

- **主动检查**：注册中心定期轮询服务端点
- **被动心跳**：服务定期发送心跳维持注册
- **状态管理**：healthy/unhealthy/unknown

### 4. 服务注销

- 正常注销：DELETE /api/v1/registry/services/{id}
- TTL 过期：自动清理
- 健康检查失败：自动标记并清理

## 存储设计

### SQLite Schema（开发/测试默认）

```sql
-- 服务表
CREATE TABLE services (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    version TEXT,
    endpoints TEXT,  -- JSON
    metadata TEXT,   -- JSON
    health_config TEXT,  -- JSON
    status TEXT DEFAULT 'unknown',
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat DATETIME,
    ttl INTEGER DEFAULT 0,
    expires_at DATETIME
);

-- 健康检查日志
CREATE TABLE health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT,
    status TEXT,
    response_time_ms INTEGER,
    error_message TEXT,
    checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_services_name ON services(name);
CREATE INDEX idx_services_status ON services(status);
CREATE INDEX idx_health_checks_service ON health_checks(service_id);
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/registry/services | 注册服务 |
| GET | /api/v1/registry/services | 列出服务 |
| GET | /api/v1/registry/services/{id} | 获取服务详情 |
| PUT | /api/v1/registry/services/{id} | 更新服务 |
| DELETE | /api/v1/registry/services/{id} | 注销服务 |
| POST | /api/v1/registry/services/{id}/heartbeat | 心跳上报 |
| GET | /api/v1/registry/services/{id}/health | 健康状态 |
| GET | /health | 注册中心自身健康 |

## 配置设计

```yaml
# /brain/infrastructure/service/service-registry/config.yaml
server:
  host: 0.0.0.0
  port: 8500

storage:
  type: sqlite  # memory | sqlite | redis
  sqlite:
    path: /data/registry.db
  redis:
    host: redis
    port: 6379
    db: 0

health_check:
  enabled: true
  interval: 30
  timeout: 5
  max_failures: 3

ttl:
  default: 60  # 默认 TTL 秒
  cleanup_interval: 300  # 清理间隔

logging:
  level: info
  format: json
```

## 与现有系统集成

### 1. 与 IPC 集成

- 注册中心启动后，向 IPC 注册自身
- Agents 可通过 IPC 查询服务位置
- 保持现有 IPC 通信不变

### 2. 与 agentctl 集成

- 服务启动时自动注册
- 服务停止时自动注销
- 支持服务依赖管理

### 3. 与网关集成

- Gateway 从注册中心动态发现后端服务
- 支持负载均衡和故障转移
- 动态路由更新

## 部署方案

### 开发环境（单容器）

```yaml
# compose.dev.yaml
services:
  service-registry:
    build: ./service-registry
    ports:
      - "8500:8500"
    volumes:
      - registry-data:/data
    environment:
      - STORAGE_TYPE=sqlite
```

### 生产环境（高可用）

```yaml
# compose.prod.yaml
services:
  service-registry:
    image: service-registry:latest
    deploy:
      replicas: 3
    environment:
      - STORAGE_TYPE=redis
      - REDIS_HOST=redis-cluster
```

## 测试策略

1. **单元测试**：API 端点、存储层、健康检查逻辑
2. **集成测试**：与现有服务集成、数据一致性
3. **E2E 测试**：完整的服务注册发现流程
4. **压力测试**：并发注册、大量服务查询

## 里程碑

1. **MVP**（本周）：基础注册/发现 API + SQLite 存储
2. **v0.2**（下周）：健康检查 + 心跳机制
3. **v0.3**（第三周）：与现有系统集成
4. **v1.0**（第四周）：生产就绪（Redis + HA）
