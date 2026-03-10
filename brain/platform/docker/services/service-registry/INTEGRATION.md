# brain_gateway 与服务注册中心集成方案

## 1. 架构目标

gateway 从静态配置转变为动态服务发现，支持后端服务的自动注册与故障转移。

```
┌─────────────┐      1. 查询服务列表      ┌─────────────────┐
│   Client    │ ─────────────────────────▶ │ Service Registry│
└─────────────┘                            │   (8500)        │
       │                                   └─────────────────┘
       │                                            │
       │ 2. 请求转发到发现的实例                    │
       │◀───────────────────────────────────────────┘
       ▼
┌─────────────┐
│ brain_gateway│ ◀── 定期刷新服务列表 (30s)
│  (动态路由)  │ ◀── 监听服务变更 (SSE/WebSocket)
└─────────────┘
       │
       │ 3. 负载均衡选择健康实例
       ▼
┌────────────────────────────────────────────┐
│  Backend Services (gateway, task-manager, etc.)  │
│  - 启动时注册到 Registry                      │
│  - 定期发送心跳                              │
│  - 停止时注销                                │
└────────────────────────────────────────────┘
```

## 2. 服务发现机制

### 2.1 Gateway 启动流程

```python
# brain_gateway 启动时
class DynamicRouter:
    def __init__(self):
        self.registry_url = os.environ.get('REGISTRY_URL', 'http://service-registry:8500')
        self.registry_api_key = os.environ.get('REGISTRY_API_KEY')
        self.service_cache = {}  # {service_name: [endpoints]}
        self.last_update = 0

    def discover_services(self):
        """从注册中心获取所有服务"""
        resp = requests.get(
            f"{self.registry_url}/api/v1/registry/services",
            headers={"X-API-Key": self.registry_api_key},
            timeout=5
        )
        services = resp.json()["services"]

        # 按名称分组
        self.service_cache = {}
        for svc in services:
            name = svc["service_name"]
            if name not in self.service_cache:
                self.service_cache[name] = []
            self.service_cache[name].append(svc)

    def get_endpoint(self, service_name, strategy="round_robin"):
        """获取服务端点（带缓存）"""
        # 缓存 30 秒
        if time.time() - self.last_update > 30:
            self.discover_services()
            self.last_update = time.time()

        services = self.service_cache.get(service_name, [])
        if not services:
            raise ServiceNotFound(service_name)

        # 负载均衡策略
        if strategy == "round_robin":
            svc = services[0]  # 简化实现
        elif strategy == "random":
            svc = random.choice(services)
        elif strategy == "least_conn":
            svc = min(services, key=lambda s: s.get("metadata", {}).get("connections", 0))

        endpoint = svc["endpoints"][0]
        return f"{endpoint['protocol']}://{endpoint['host']}:{endpoint['port']}"
```

### 2.2 动态路由配置

```python
# brain_gateway 路由配置
from flask import Flask, request

app = Flask(__name__)
router = DynamicRouter()

@app.route('/<service_name>/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def dynamic_proxy(service_name, path):
    """动态代理到后端服务"""

    # 1. 发现服务
    try:
        backend_url = router.get_endpoint(service_name)
    except ServiceNotFound:
        return {"error": f"Service {service_name} not found"}, 503

    # 2. 转发请求
    target = f"{backend_url}/{path}"
    resp = requests.request(
        method=request.method,
        url=target,
        headers=request.headers,
        data=request.get_data(),
        timeout=30,
        stream=True
    )

    # 3. 流式返回响应
    return Response(
        resp.iter_content(chunk_size=8192),
        status=resp.status_code,
        headers=dict(resp.headers)
    )
```

## 3. 认证对接方式

### 3.1 方案选择

| 方案 | 说明 | 推荐度 |
|------|------|--------|
| **共享 API Key** | gateway 和 registry 共享同一 API Key | ⭐⭐⭐ 推荐 |
| 服务账号 | gateway 使用独立账号，registry 分配权限 | ⭐⭐ 较复杂 |
| mTLS | 双向 TLS 证书认证 | ⭐ 过重 |

### 3.2 共享 API Key 实现

```yaml
# compose.yaml 环境变量配置
services:
  service-registry:
    environment:
      - AUTH_REQUIRED=true
      - REGISTRY_API_KEY=${REGISTRY_API_KEY}

  brain_gateway:
    environment:
      - REGISTRY_URL=http://service-registry:8500
      - REGISTRY_API_KEY=${REGISTRY_API_KEY}  # 共享密钥
```

### 3.3 密钥管理

```bash
# .env 文件（由 PMO/运维管理，不提交到 git）
REGISTRY_API_KEY=xk-agent-infra-registry-2026-secure-key

# 密钥轮换流程：
# 1. PMO 生成新密钥
# 2. 更新 .env 文件
# 3. 重启 registry（热重载支持）
# 4. 滚动重启 gateway
```

## 4. 故障处理

### 4.1 Registry 不可用

```python
class DynamicRouter:
    def get_endpoint(self, service_name):
        try:
            return self._fetch_from_registry(service_name)
        except (requests.Timeout, requests.ConnectionError):
            # 使用缓存（可能过期，但可用）
            if service_name in self.service_cache:
                logger.warning(f"Using stale cache for {service_name}")
                return self._select_endpoint(self.service_cache[service_name])
            raise ServiceUnavailable(service_name)
```

### 4.2 Backend 故障转移

```python
def proxy_with_retry(service_name, path, request):
    """带故障转移的代理"""
    services = router.get_all_endpoints(service_name)

    for svc in services:
        try:
            endpoint = svc["endpoints"][0]
            url = f"{endpoint['protocol']}://{endpoint['host']}:{endpoint['port']}/{path}"
            return requests.request(method=request.method, url=url, timeout=10)
        except requests.RequestException:
            continue  # 尝试下一个实例

    raise AllBackendsFailed(service_name)
```

## 5. 集成验证计划

| 步骤 | 验证内容 | 预期结果 |
|------|----------|----------|
| 1 | gateway 启动时发现服务 | 缓存中有 registry 返回的服务列表 |
| 2 | 请求转发 | /gateway/status → backend gateway |
| 3 | 服务下线 | 注销后 gateway 不再路由到该实例 |
| 4 | 认证失败 | 无效 API Key 返回 403 |
| 5 | registry 离线 | gateway 使用缓存继续服务 |

## 6. 部署步骤

```bash
# 1. 启动 registry（已验证）
docker run -d --name service-registry \
  -p 8500:8500 \
  -e REGISTRY_API_KEY=${REGISTRY_API_KEY} \
  service-registry:v1.0

# 2. 修改 gateway 配置（添加环境变量）
# 3. 重启 gateway
# 4. 验证动态路由

# 测试命令
curl http://localhost:8080/gateway/health
curl http://localhost:8080/task-manager/tasks
```

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| registry 单点故障 | 后期部署 Redis 集群 + registry 多实例 |
| 缓存过期导致路由到失败节点 | 缩短缓存时间 + 快速健康检查 |
| API Key 泄露 | 定期轮换 + 只在内网暴露 registry |

---

**建议下一步**：实施 gateway 修改，进行联调测试。