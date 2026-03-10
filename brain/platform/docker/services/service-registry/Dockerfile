FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py storage.py gunicorn.conf.py ./

# 创建数据目录
RUN mkdir -p /data

# 暴露端口
EXPOSE 8500

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/health')" || exit 1

# 使用 Gunicorn 启动（生产级 WSGI 服务器）
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
