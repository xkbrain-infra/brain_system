"""
存储层抽象
支持 SQLite 和 Redis 两种后端
"""

import json
import sqlite3
from datetime import datetime
from abc import ABC, abstractmethod


class Storage(ABC):
    """存储抽象基类"""

    @abstractmethod
    def init(self):
        """初始化存储"""
        pass

    @abstractmethod
    def save_service(self, service_data):
        """保存服务"""
        pass

    @abstractmethod
    def get_service(self, service_id):
        """获取服务"""
        pass

    @abstractmethod
    def list_services(self, name=None, healthy_only=False):
        """列出服务"""
        pass

    @abstractmethod
    def delete_service(self, service_id):
        """删除服务"""
        pass

    @abstractmethod
    def update_heartbeat(self, service_id, expires_at):
        """更新心跳"""
        pass

    @abstractmethod
    def cleanup_expired(self):
        """清理过期服务"""
        pass


class SQLiteStorage(Storage):
    """SQLite 存储实现"""

    def __init__(self, db_path):
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        """初始化数据库"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT,
                version TEXT,
                endpoints TEXT,
                metadata TEXT,
                health_config TEXT,
                status TEXT DEFAULT 'unknown',
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_heartbeat DATETIME,
                ttl INTEGER DEFAULT 0,
                expires_at DATETIME
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT,
                status TEXT,
                response_time_ms INTEGER,
                error_message TEXT,
                checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_services_name ON services(name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_services_status ON services(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_services_expires ON services(expires_at)')

        conn.commit()
        conn.close()

    def save_service(self, service_data):
        """保存或更新服务"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO services
            (id, name, type, version, endpoints, metadata, health_config, status, ttl, expires_at, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            service_data['id'],
            service_data['name'],
            service_data.get('type'),
            service_data.get('version'),
            json.dumps(service_data.get('endpoints', [])),
            json.dumps(service_data.get('metadata', {})),
            json.dumps(service_data.get('health_config', {})),
            service_data.get('status', 'unknown'),
            service_data.get('ttl', 0),
            service_data.get('expires_at'),
            service_data.get('last_heartbeat')
        ))

        conn.commit()
        conn.close()

    def get_service(self, service_id):
        """获取服务详情"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM services WHERE id = ?', (service_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return self._row_to_dict(row)

    def list_services(self, name=None, healthy_only=False):
        """列出服务"""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = 'SELECT * FROM services WHERE 1=1'
        params = []

        if name:
            query += ' AND name = ?'
            params.append(name)

        if healthy_only:
            query += ' AND status = ?'
            params.append('healthy')

        # 排除已过期
        query += ' AND (expires_at IS NULL OR expires_at > ?)'
        params.append(datetime.utcnow().isoformat())

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def delete_service(self, service_id):
        """删除服务"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM services WHERE id = ?', (service_id,))
        conn.commit()
        conn.close()

    def update_heartbeat(self, service_id, expires_at):
        """更新心跳"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE services
            SET last_heartbeat = ?, expires_at = ?, status = ?
            WHERE id = ?
        ''', (datetime.utcnow().isoformat(), expires_at.isoformat() if expires_at else None, 'healthy', service_id))

        conn.commit()
        conn.close()

    def cleanup_expired(self):
        """清理过期服务"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM services
            WHERE expires_at IS NOT NULL AND expires_at < ?
        ''', (datetime.utcnow().isoformat(),))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted

    def _row_to_dict(self, row):
        """将数据库行转换为字典"""
        return {
            "service_id": row['id'],
            "service_name": row['name'],
            "type": row['type'],
            "version": row['version'],
            "endpoints": json.loads(row['endpoints']) if row['endpoints'] else [],
            "metadata": json.loads(row['metadata']) if row['metadata'] else {},
            "health_config": json.loads(row['health_config']) if row['health_config'] else {},
            "status": row['status'],
            "registered_at": row['registered_at'],
            "last_heartbeat": row['last_heartbeat'],
            "ttl": row['ttl'],
            "expires_at": row['expires_at']
        }


class RedisStorage(Storage):
    """Redis 存储实现"""

    def __init__(self, host, port, db):
        import redis
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.key_prefix = "registry:service:"

    def init(self):
        """Redis 不需要初始化表结构"""
        self.client.ping()

    def _get_key(self, service_id):
        return f"{self.key_prefix}{service_id}"

    def save_service(self, service_data):
        """保存服务到 Redis"""
        key = self._get_key(service_data['id'])
        self.client.hset(key, mapping={
            'data': json.dumps(service_data),
            'name': service_data['name'],
            'status': service_data.get('status', 'unknown'),
            'expires_at': service_data.get('expires_at', '')
        })

        # 设置过期时间（如果有）
        if service_data.get('expires_at'):
            try:
                from datetime import datetime
                expires = datetime.fromisoformat(service_data['expires_at'])
                ttl_seconds = int((expires - datetime.utcnow()).total_seconds())
                if ttl_seconds > 0:
                    self.client.expire(key, ttl_seconds)
            except:
                pass

    def get_service(self, service_id):
        """从 Redis 获取服务"""
        key = self._get_key(service_id)
        data = self.client.hget(key, 'data')
        if data:
            return json.loads(data)
        return None

    def list_services(self, name=None, healthy_only=False):
        """列出所有服务"""
        services = []
        for key in self.client.scan_iter(match=f"{self.key_prefix}*"):
            data = self.client.hget(key, 'data')
            if data:
                service = json.loads(data)
                # 过滤
                if name and service.get('name') != name:
                    continue
                if healthy_only and service.get('status') != 'healthy':
                    continue
                services.append(service)
        return services

    def delete_service(self, service_id):
        """删除服务"""
        key = self._get_key(service_id)
        self.client.delete(key)

    def update_heartbeat(self, service_id, expires_at):
        """更新心跳"""
        service = self.get_service(service_id)
        if service:
            service['last_heartbeat'] = datetime.utcnow().isoformat()
            service['status'] = 'healthy'
            if expires_at:
                service['expires_at'] = expires_at.isoformat()
            self.save_service(service)

    def cleanup_expired(self):
        """Redis 自动过期，无需手动清理"""
        return 0


def get_storage(config):
    """工厂函数：根据配置获取存储实例"""
    if config.STORAGE_TYPE == 'redis':
        return RedisStorage(config.REDIS_HOST, config.REDIS_PORT, config.REDIS_DB)
    else:
        return SQLiteStorage(config.SQLITE_PATH)
