"""
brain_gateway - Python 版本（用于集成测试）
支持从 Service Registry 动态发现后端服务
"""

import os
import json
import time
import logging
import itertools
import requests
from flask import Flask, request, Response
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


class ServiceRegistryClient:
    """服务注册中心客户端"""

    def __init__(self):
        self.registry_url = os.environ.get(
            'REGISTRY_URL',
            'http://service-registry:8500'
        )
        self.api_key = os.environ.get('REGISTRY_API_KEY')
        self.cache_ttl = int(os.environ.get('REGISTRY_CACHE_TTL', '30'))

        self._cache = {}
        self._last_update = 0
        self._round_robin_counters = {}  # PMO 意见 a): 真正的 round_robin

    def _get_headers(self):
        """获取请求头"""
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        return headers

    def discover_services(self, force=False):
        """从注册中心获取服务列表"""
        now = time.time()

        # 缓存未过期且非强制刷新
        if not force and (now - self._last_update) < self.cache_ttl:
            return self._cache

        try:
            resp = requests.get(
                f"{self.registry_url}/api/v1/registry/services",
                headers=self._get_headers(),
                timeout=5
            )
            resp.raise_for_status()
            services = resp.json().get('services', [])

            # 按服务名分组
            self._cache = {}
            for svc in services:
                name = svc.get('service_name')
                if name not in self._cache:
                    self._cache[name] = []
                self._cache[name].append(svc)

            self._last_update = now
            logger.info(f"Service cache updated: {len(self._cache)} services")

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch from registry: {e}")
            # 缓存降级：如果缓存存在但过期，继续使用
            if self._cache:
                logger.warning("Using stale cache")
            else:
                raise ServiceUnavailable("Registry unavailable and no cache")

        return self._cache

    def get_endpoint(self, service_name, strategy='round_robin'):
        """
        获取服务端点

        strategy: round_robin | random | first
        """
        services = self.discover_services().get(service_name, [])

        if not services:
            raise ServiceNotFound(f"Service {service_name} not found")

        if strategy == 'round_robin':
            # PMO 意见 a): 真正的 round_robin 实现
            counter = self._round_robin_counters.get(service_name, 0)
            svc = services[counter % len(services)]
            self._round_robin_counters[service_name] = counter + 1

        elif strategy == 'random':
            import random
            svc = random.choice(services)

        else:  # first
            svc = services[0]

        endpoints = svc.get('endpoints', [])
        if not endpoints:
            raise ServiceNotFound(f"Service {service_name} has no endpoints")

        ep = endpoints[0]
        return f"{ep['protocol']}://{ep['host']}:{ep['port']}"

    def get_all_endpoints(self, service_name):
        """获取服务的所有端点（用于故障转移）"""
        services = self.discover_services().get(service_name, [])
        endpoints = []
        for svc in services:
            for ep in svc.get('endpoints', []):
                endpoints.append({
                    'url': f"{ep['protocol']}://{ep['host']}:{ep['port']}",
                    'service_id': svc.get('service_id'),
                    'status': svc.get('status')
                })
        return endpoints


class ServiceNotFound(Exception):
    pass


class ServiceUnavailable(Exception):
    pass


# 全局 registry 客户端
registry = ServiceRegistryClient()


# PMO 意见 c): 需要过滤的 hop-by-hop headers
HOP_BY_HOP_HEADERS = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'transfer-encoding',
    'upgrade',
    'host',  # Host 需要重新设置为目标地址
}


def filter_headers(headers):
    """过滤 hop-by-hop headers"""
    return {
        k: v for k, v in headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }


@app.route('/health', methods=['GET'])
def health():
    """网关健康检查"""
    try:
        registry.discover_services()
        return {
            'status': 'healthy',
            'service': 'brain_gateway',
            'registry_connected': True
        }
    except Exception as e:
        return {
            'status': 'degraded',
            'service': 'brain_gateway',
            'registry_connected': False,
            'error': str(e)
        }, 503


@app.route('/<service_name>/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def dynamic_proxy(service_name, path):
    """
    动态代理到后端服务

    URL 格式: /<service_name>/<path>
    示例: /brain_gateway/api/v1/status
          /task_manager/tasks/123
    """
    # 特殊路径：registry 相关接口直接返回
    if service_name == '_registry':
        return {'cache': registry._cache, 'last_update': registry._last_update}

    try:
        # 1. 获取所有可用端点（用于故障转移）
        endpoints = registry.get_all_endpoints(service_name)

        if not endpoints:
            return {'error': f'Service {service_name} not found'}, 503

        # 2. 尝试每个端点（故障转移）
        last_error = None

        for ep in endpoints:
            try:
                target_url = f"{ep['url']}/{path}"
                query_string = request.query_string.decode()
                if query_string:
                    target_url += f"?{query_string}"

                # PMO 意见 c): 过滤 headers
                headers = filter_headers(dict(request.headers))

                logger.info(f"Proxying to {target_url}")

                resp = requests.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    data=request.get_data(),
                    timeout=30,
                    stream=True
                )

                # 流式返回响应
                return Response(
                    resp.iter_content(chunk_size=8192),
                    status=resp.status_code,
                    headers=dict(resp.headers)
                )

            except requests.RequestException as e:
                logger.warning(f"Endpoint {ep['url']} failed: {e}")
                last_error = e
                continue  # 尝试下一个端点

        # 所有端点都失败
        return {
            'error': f'All backends for {service_name} failed',
            'last_error': str(last_error)
        }, 503

    except ServiceNotFound as e:
        return {'error': str(e)}, 503
    except Exception as e:
        logger.exception("Proxy error")
        return {'error': 'Internal error', 'detail': str(e)}, 500


@app.route('/<service_name>/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def dynamic_proxy_root(service_name):
    """代理到根路径"""
    return dynamic_proxy(service_name, '')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    host = os.environ.get('HOST', '0.0.0.0')

    logger.info(f"Starting brain_gateway (Python) on {host}:{port}")
    logger.info(f"Registry URL: {registry.registry_url}")
    logger.info(f"Cache TTL: {registry.cache_ttl}s")

    app.run(host=host, port=port, threaded=True)
