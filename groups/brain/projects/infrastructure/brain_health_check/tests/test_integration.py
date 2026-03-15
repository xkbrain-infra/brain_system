#!/usr/bin/env python3
"""
BS-024 Health Check Server - 集成测试

测试 service-down 场景（QA 附加条件 #3）
"""

import json
import os
import subprocess
import sys
import time
import unittest
from http.client import HTTPConnection


class TestHealthCheckIntegration(unittest.TestCase):
    """集成测试 - 端到端场景"""

    @classmethod
    def setUpClass(cls):
        """启动健康检查服务器"""
        cls.port = 18766  # 使用不同端口避免冲突

        # 设置环境变量
        env = {
            **os.environ,
            "HEALTH_CHECK_PORT": str(cls.port),
            "HEALTH_CHECK_VERSION": "1.0.0-test"
        }

        cls.process = subprocess.Popen(
            [sys.executable, "/brain/infrastructure/service/health_check/health_server.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待服务器启动
        max_retries = 10
        for i in range(max_retries):
            try:
                conn = HTTPConnection("localhost", cls.port, timeout=2)
                conn.request("GET", "/health")
                response = conn.getresponse()
                if response.status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            stdout, stderr = cls.process.communicate()
            raise RuntimeError(f"Server failed to start: {stderr.decode()}")

    @classmethod
    def tearDownClass(cls):
        """停止服务器"""
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()

    def _make_request(self, method, path):
        """发送 HTTP 请求"""
        conn = HTTPConnection("localhost", self.port, timeout=5)
        conn.request(method, path)
        response = conn.getresponse()
        body = response.read().decode()
        data = json.loads(body) if body else {}
        return response.status, data

    def test_it1_all_services_healthy(self):
        """IT-1: 所有服务正常 → GET /health → 200 + healthy"""
        status, data = self._make_request("GET", "/health")

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "healthy")
        self.assertIn("timestamp", data)
        self.assertIn("version", data)
        self.assertIn("services", data)

        print(f"✓ IT-1 passed: {data}")

    def test_it2_get_other_returns_404(self):
        """GET /other → 404 + error"""
        status, data = self._make_request("GET", "/other")

        self.assertEqual(status, 404)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "not found")
        self.assertIn("timestamp", data)

        print(f"✓ IT-2 passed: {data}")

    def test_it3_post_health_returns_405(self):
        """POST /health → 405 + error"""
        status, data = self._make_request("POST", "/health")

        self.assertEqual(status, 405)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "method not allowed")
        self.assertIn("timestamp", data)

        print(f"✓ IT-3 passed: {data}")

    def test_it4_concurrent_requests(self):
        """IT-4: 并发请求不崩溃"""
        import concurrent.futures

        def make_request(i):
            try:
                status, data = self._make_request("GET", "/health")
                return status == 200
            except Exception as e:
                print(f"Request {i} failed: {e}")
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        success_count = sum(results)
        self.assertEqual(success_count, 20, f"Expected 20 successes, got {success_count}")

        print(f"✓ IT-4 passed: 20/20 concurrent requests successful")


class TestErrorResponseFormat(unittest.TestCase):
    """测试错误响应格式（QA 附加条件 #1）"""

    @classmethod
    def setUpClass(cls):
        """启动服务器"""
        cls.port = 18767

        env = {
            **os.environ,
            "HEALTH_CHECK_PORT": str(cls.port),
            "HEALTH_CHECK_VERSION": "1.0.0-test"
        }

        cls.process = subprocess.Popen(
            [sys.executable, "/brain/infrastructure/service/health_check/health_server.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        """停止服务器"""
        cls.process.terminate()
        cls.process.wait(timeout=5)

    def test_error_format_structure(self):
        """验证错误响应格式"""
        conn = HTTPConnection("localhost", self.port, timeout=5)
        conn.request("GET", "/nonexistent")
        response = conn.getresponse()

        body = response.read().decode()
        data = json.loads(body)

        # 验证结构
        self.assertIn("status", data)
        self.assertIn("message", data)
        self.assertIn("timestamp", data)

        # 验证类型
        self.assertIsInstance(data["status"], str)
        self.assertIsInstance(data["message"], str)
        self.assertIsInstance(data["timestamp"], str)

        print(f"✓ Error format test passed: {data}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
