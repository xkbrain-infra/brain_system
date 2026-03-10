"""
服务注册中心 - 生产级实现
Production-ready Service Registry with:
- Gunicorn WSGI server
- API Key authentication
- Prometheus metrics
- Structured logging
"""

import os
import sys
import json
import uuid
import time
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from threading import Thread
from functools import wraps

from flask import Flask, request, jsonify, g
from prometheus_client import Counter, Histogram, Info, Gauge, generate_latest, CONTENT_TYPE_LATEST

# 导入存储层
from storage import get_storage

# Flask 应用
app = Flask(__name__)

# ============ 配置 ============

class Config:
    """应用配置"""
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 8500))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

    # 认证配置
    API_KEY = os.environ.get('REGISTRY_API_KEY')
    AUTH_REQUIRED = os.environ.get('AUTH_REQUIRED', 'true').lower() == 'true'
    READONLY_AUTH = os.environ.get('READONLY_AUTH', 'false').lower() == 'true'

    # 存储配置
    STORAGE_TYPE = os.environ.get('STORAGE_TYPE', 'sqlite')
    SQLITE_PATH = os.environ.get('SQLITE_PATH', '/data/registry.db')
    REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    REDIS_DB = int(os.environ.get('REDIS_DB', 0))

    # TTL 配置
    DEFAULT_TTL = int(os.environ.get('DEFAULT_TTL', 60))
    CLEANUP_INTERVAL = int(os.environ.get('CLEANUP_INTERVAL', 60))

# 配置日志
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============ Prometheus 指标 ============

# 服务注册指标
REGISTRY_REQUESTS = Counter(
    'registry_requests_total',
    'Total requests to registry',
    ['method', 'endpoint', 'status']
)

REGISTRY_REQUEST_DURATION = Histogram(
    'registry_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

SERVICES_REGISTERED = Counter(
    'registry_services_registered_total',
    'Total services registered',
    ['service_type']
)

SERVICES_DEREGISTERED = Counter(
    'registry_services_deregistered_total',
    'Total services deregistered'
)

ACTIVE_SERVICES = Gauge(
    'registry_active_services',
    'Number of active services',
    ['service_name']
)

HEARTBEATS_RECEIVED = Counter(
    'registry_heartbeats_received_total',
    'Total heartbeats received',
    ['service_name']
)

# 应用信息
APP_INFO = Info('registry_app', 'Service Registry Application Info')
APP_INFO.info({'version': '1.0.0', 'storage': Config.STORAGE_TYPE})

# ============ 存储层 ============

storage = None

def init_storage():
    """初始化存储"""
    global storage
    storage = get_storage(Config)
    storage.init()
    logger.info(f"Storage initialized: {Config.STORAGE_TYPE}")

# ============ 认证中间件 ============

def require_auth(f):
    """API Key 认证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not Config.AUTH_REQUIRED:
            return f(*args, **kwargs)

        # 只读操作可能不需要认证
        if request.method == 'GET' and not Config.READONLY_AUTH:
            return f(*args, **kwargs)

        api_key = request.headers.get('X-API-Key')
        if not api_key:
            logger.warning(f"Missing API key from {request.remote_addr}")
            return jsonify({"error": "Missing API key"}), 401

        # 简单的 API Key 验证（生产环境建议使用更安全的方案）
        if not Config.API_KEY:
            logger.error("API_KEY not configured but AUTH_REQUIRED is true")
            return jsonify({"error": "Server misconfigured"}), 500

        if not hmac.compare_digest(api_key, Config.API_KEY):
            logger.warning(f"Invalid API key from {request.remote_addr}")
            return jsonify({"error": "Invalid API key"}), 403

        return f(*args, **kwargs)
    return decorated_function

# ============ 请求钩子 ============

@app.before_request
def before_request():
    """请求前处理"""
    g.start_time = time.time()

@app.after_request
def after_request(response):
    """请求后处理 - 记录指标"""
    if hasattr(g, 'start_time'):
        duration = time.time() - g.start_time
        endpoint = request.endpoint or 'unknown'
        REGISTRY_REQUEST_DURATION.labels(
            method=request.method,
            endpoint=endpoint
        ).observe(duration)

    REGISTRY_REQUESTS.labels(
        method=request.method,
        endpoint=request.endpoint or 'unknown',
        status=response.status_code
    ).inc()

    return response

# ============ API 端点 ============

@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "service": "registry",
        "version": "1.0.0",
        "storage": Config.STORAGE_TYPE,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus 指标端点"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

@app.route('/api/v1/registry/services', methods=['POST'])
@require_auth
def register_service():
    """注册服务"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    service_id = data.get('service_id') or str(uuid.uuid4())
    name = data.get('service_name')

    if not name:
        return jsonify({"error": "service_name is required"}), 400

    ttl = data.get('ttl', Config.DEFAULT_TTL)
    expires_at = None
    if ttl > 0:
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)

    service_data = {
        'id': service_id,
        'name': name,
        'type': data.get('service_type'),
        'version': data.get('version'),
        'endpoints': data.get('endpoints', []),
        'metadata': data.get('metadata', {}),
        'health_config': data.get('health_check', {}),
        'ttl': ttl,
        'expires_at': expires_at.isoformat() if expires_at else None,
        'status': 'healthy',
        'last_heartbeat': datetime.utcnow().isoformat()
    }

    try:
        storage.save_service(service_data)
        SERVICES_REGISTERED.labels(service_type=service_data['type'] or 'unknown').inc()
        ACTIVE_SERVICES.labels(service_name=name).inc()

        logger.info(f"Service registered: {service_id} ({name})")
        return jsonify({
            "service_id": service_id,
            "status": "registered",
            "expires_at": service_data['expires_at']
        }), 201
    except Exception as e:
        logger.error(f"Failed to register service: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/registry/services', methods=['GET'])
def list_services():
    """列出服务"""
    name = request.args.get('name')
    healthy_only = request.args.get('healthy', 'false').lower() == 'true'

    try:
        services = storage.list_services(name=name, healthy_only=healthy_only)
        return jsonify({"services": services, "count": len(services)})
    except Exception as e:
        logger.error(f"Failed to list services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/registry/services/<service_id>', methods=['GET'])
def get_service(service_id):
    """获取服务详情"""
    try:
        service = storage.get_service(service_id)
        if not service:
            return jsonify({"error": "Service not found"}), 404
        return jsonify(service)
    except Exception as e:
        logger.error(f"Failed to get service: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/registry/services/<service_id>', methods=['PUT'])
@require_auth
def update_service(service_id):
    """更新服务"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    try:
        existing = storage.get_service(service_id)
        if not existing:
            return jsonify({"error": "Service not found"}), 404

        # 合并更新
        existing.update(data)
        storage.save_service(existing)

        logger.info(f"Service updated: {service_id}")
        return jsonify({"service_id": service_id, "status": "updated"})
    except Exception as e:
        logger.error(f"Failed to update service: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/registry/services/<service_id>', methods=['DELETE'])
@require_auth
def deregister_service(service_id):
    """注销服务"""
    try:
        service = storage.get_service(service_id)
        if service:
            storage.delete_service(service_id)
            SERVICES_DEREGISTERED.inc()
            ACTIVE_SERVICES.labels(service_name=service['name']).dec()

        logger.info(f"Service deregistered: {service_id}")
        return jsonify({"status": "deregistered", "service_id": service_id})
    except Exception as e:
        logger.error(f"Failed to deregister service: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/registry/services/<service_id>/heartbeat', methods=['POST'])
@require_auth
def heartbeat(service_id):
    """心跳上报"""
    try:
        service = storage.get_service(service_id)
        if not service:
            return jsonify({"error": "Service not found"}), 404

        ttl = service.get('ttl', Config.DEFAULT_TTL)
        expires_at = None
        if ttl > 0:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)

        storage.update_heartbeat(service_id, expires_at)
        HEARTBEATS_RECEIVED.labels(service_name=service['name']).inc()

        return jsonify({
            "status": "ok",
            "expires_at": expires_at.isoformat() if expires_at else None
        })
    except Exception as e:
        logger.error(f"Heartbeat failed: {e}")
        return jsonify({"error": str(e)}), 500

# ============ 后台任务 ============

def cleanup_expired():
    """清理过期服务"""
    while True:
        time.sleep(Config.CLEANUP_INTERVAL)
        try:
            deleted = storage.cleanup_expired()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired services")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ============ 启动 ============

def create_app():
    """创建应用（用于 Gunicorn）"""
    init_storage()

    # 启动清理线程
    cleanup_thread = Thread(target=cleanup_expired, daemon=True)
    cleanup_thread.start()

    logger.info(f"Service Registry initialized with {Config.STORAGE_TYPE} storage")
    return app

if __name__ == '__main__':
    # 开发模式直接运行
    app = create_app()
    logger.info(f"Starting development server on {Config.HOST}:{Config.PORT}")
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
