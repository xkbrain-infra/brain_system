#!/usr/bin/env python3
"""
BS-024 Health Check Server - 单元测试

测试 M1 (HealthRequestHandler) 和 M5 (ServerMain) 的基本功能
"""

import importlib
import json
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from http.client import HTTPConnection

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置测试环境变量
os.environ["HEALTH_CHECK_PORT"] = "18765"
os.environ["HEALTH_CHECK_VERSION"] = "1.0.0-test"


class TestHealthRequestHandler(unittest.TestCase):
    """测试 HealthRequestHandler"""

    def setUp(self):
        """每个测试前设置"""
        # 动态导入模块（避免缓存问题）
        import health_server
        importlib.reload(health_server)
        self.handler_class = health_server.HealthRequestHandler

    def _create_mock_request(self, path, method="GET"):
        """创建模拟的 HTTP 请求"""
        mock_wfile = MagicMock()
        mock_wfile.write = Mock()

        mock_rfile = MagicMock()

        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = {}
        handler.wfile = mock_wfile
        handler.rfile = mock_rfile
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()

        return handler

    def test_get_health_returns_200(self):
        """GET /health → HTTP 200"""
        handler = self._create_mock_request("/health", "GET")

        with patch.object(handler, '_send_json') as mock_send:
            handler.do_GET()
            mock_send.assert_called_once()
            status_code = mock_send.call_args[0][0]
            self.assertEqual(status_code, 200)

    def test_get_health_returns_valid_json(self):
        """GET /health 返回合法的 JSON"""
        handler = self._create_mock_request("/health", "GET")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_GET()

        self.assertEqual(response_data['status_code'], 200)
        data = response_data['data']

        # 验证 JSON 结构
        self.assertIn("status", data)
        self.assertIn("timestamp", data)
        self.assertIn("version", data)
        self.assertIn("services", data)

        # 验证响应格式
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["version"], "1.0.0-test")
        # 注意：实际运行时 services 包含真实服务状态，不强制要求为空

    def test_get_other_returns_404(self):
        """GET /other → HTTP 404"""
        handler = self._create_mock_request("/other", "GET")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_GET()

        self.assertEqual(response_data['status_code'], 404)
        data = response_data['data']

        # 验证错误格式
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "not found")
        self.assertIn("timestamp", data)

    def test_post_health_returns_405(self):
        """POST /health → HTTP 405"""
        handler = self._create_mock_request("/health", "POST")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_POST()

        self.assertEqual(response_data['status_code'], 405)
        data = response_data['data']

        # 验证错误格式
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "method not allowed")
        self.assertIn("timestamp", data)

    def test_put_health_returns_405(self):
        """PUT /health → HTTP 405"""
        handler = self._create_mock_request("/health", "PUT")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_PUT()

        self.assertEqual(response_data['status_code'], 405)

    def test_delete_health_returns_405(self):
        """DELETE /health → HTTP 405"""
        handler = self._create_mock_request("/health", "DELETE")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_DELETE()

        self.assertEqual(response_data['status_code'], 405)

    def test_patch_health_returns_405(self):
        """PATCH /health → HTTP 405"""
        handler = self._create_mock_request("/health", "PATCH")

        response_data = {}
        def capture_response(status_code, data):
            response_data['status_code'] = status_code
            response_data['data'] = data

        with patch.object(handler, '_send_json', side_effect=capture_response):
            handler.do_PATCH()

        self.assertEqual(response_data['status_code'], 405)


class TestServerMain(unittest.TestCase):
    """测试 ServerMain"""

    def test_uses_threading_httpserver(self):
        """验证使用 ThreadingHTTPServer"""
        # 直接检查源代码中是否使用 ThreadingHTTPServer
        with open('/brain/infrastructure/service/health_check/health_server.py', 'r') as f:
            source_code = f.read()

        self.assertIn('ThreadingHTTPServer', source_code,
                      "health_server.py should use ThreadingHTTPServer")

    def test_port_from_environment(self):
        """验证端口从环境变量读取"""
        os.environ["HEALTH_CHECK_PORT"] = "19999"

        import health_server
        importlib.reload(health_server)

        self.assertEqual(health_server.HEALTH_CHECK_PORT, 19999)

        # 恢复默认
        os.environ["HEALTH_CHECK_PORT"] = "18765"

    def test_ipc_socket_from_environment(self):
        """验证 IPC socket 路径从环境变量读取"""
        os.environ["BRAIN_IPC_SOCKET"] = "/tmp/test_ipc.sock"

        import health_server
        importlib.reload(health_server)

        self.assertEqual(health_server.BRAIN_IPC_SOCKET, "/tmp/test_ipc.sock")

        # 恢复默认
        os.environ["BRAIN_IPC_SOCKET"] = "/tmp/brain_ipc.sock"

    def test_version_from_environment(self):
        """验证版本号从环境变量读取"""
        os.environ["HEALTH_CHECK_VERSION"] = "2.0.0-test"

        import health_server
        importlib.reload(health_server)

        self.assertEqual(health_server.HEALTH_CHECK_VERSION, "2.0.0-test")

        # 恢复默认
        os.environ["HEALTH_CHECK_VERSION"] = "1.0.0-test"


class TestIntegration(unittest.TestCase):
    """集成测试 - 需要启动服务器"""

    @classmethod
    def setUpClass(cls):
        """启动测试服务器"""
        import subprocess
        import time

        cls.port = 18765
        cls.process = subprocess.Popen(
            [sys.executable, "/brain/infrastructure/service/health_check/health_server.py"],
            env={
                **os.environ,
                "HEALTH_CHECK_PORT": str(cls.port),
                "HEALTH_CHECK_VERSION": "1.0.0-test"
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待服务器启动
        time.sleep(1)

        # 检查进程是否启动
        if cls.process.poll() is not None:
            stdout, stderr = cls.process.communicate()
            raise RuntimeError(f"Server failed to start: {stderr.decode()}")

    @classmethod
    def tearDownClass(cls):
        """停止测试服务器"""
        cls.process.terminate()
        cls.process.wait(timeout=5)

    def test_get_health_via_http(self):
        """GET /health 通过 HTTP 返回 200"""
        conn = HTTPConnection("localhost", self.port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()

        self.assertEqual(response.status, 200)

        body = response.read().decode()
        data = json.loads(body)

        self.assertEqual(data["status"], "healthy")
        self.assertIn("timestamp", data)
        self.assertEqual(data["version"], "1.0.0-test")

    def test_get_other_via_http(self):
        """GET /other 通过 HTTP 返回 404"""
        conn = HTTPConnection("localhost", self.port, timeout=5)
        conn.request("GET", "/other")
        response = conn.getresponse()

        self.assertEqual(response.status, 404)

        body = response.read().decode()
        data = json.loads(body)

        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "not found")

    def test_post_health_via_http(self):
        """POST /health 通过 HTTP 返回 405"""
        conn = HTTPConnection("localhost", self.port, timeout=5)
        conn.request("POST", "/health")
        response = conn.getresponse()

        self.assertEqual(response.status, 405)

        body = response.read().decode()
        data = json.loads(body)

        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "method not allowed")


if __name__ == "__main__":
    unittest.main()
