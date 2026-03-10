"""
Gunicorn 配置文件
"""
import os
import multiprocessing

# 服务器绑定
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', '8500')}"

# Worker 配置
workers = int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
worker_connections = 1000
timeout = int(os.environ.get('GUNICORN_TIMEOUT', 30))
keepalive = 5

# 日志配置
accesslog = "-"  # 输出到 stdout
errorlog = "-"   # 输出到 stderr
loglevel = os.environ.get('LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程名称
proc_name = "service-registry"

# 预加载应用（节省内存）
preload_app = True

# 优雅重启
graceful_timeout = 30

# 最大请求数（防止内存泄漏）
max_requests = 10000
max_requests_jitter = 1000


def on_starting(server):
    """服务器启动前调用"""
    pass


def on_reload(server):
    """重新加载配置时调用"""
    pass


def when_ready(server):
    """服务器就绪时调用"""
    pass


def worker_int(worker):
    """Worker 收到 SIGINT 或 SIGQUIT 时调用"""
    pass


def on_exit(server):
    """服务器退出时调用"""
    pass
