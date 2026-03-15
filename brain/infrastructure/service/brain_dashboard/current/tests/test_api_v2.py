"""API Tests for Dashboard V2 - T12 Implementation.

pytest-based tests with mocking for external dependencies.
Coverage target: >80%
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, '/brain/sandbox/brain_dashboard_20260311/src')

from app import app


# Create test client
client = TestClient(app)


# ============== Fixtures ==============

@pytest.fixture
def mock_gateway_stats():
    """Mock gateway stats response."""
    return {
        "requests_total": 12345,
        "requests_per_sec": 42.5,
        "avg_latency_ms": 15.3,
        "p50_latency_ms": 10.0,
        "p95_latency_ms": 25.0,
        "p99_latency_ms": 50.0,
        "error_rate": 0.02,
        "errors_total": 247,
        "active_connections": 15
    }


@pytest.fixture
def mock_gateway_routes():
    """Mock gateway routes response."""
    return {
        "platforms": {"telegram": "agent-brain_frontdesk"},
        "keywords": [
            {"pattern": "(?i)(deploy|release)", "target": "agent-system_devops"}
        ],
        "default": "agent-brain_frontdesk"
    }


@pytest.fixture
def mock_registry_data():
    """Mock registry data."""
    return {
        "agents_registry": {"version": "1.0"},
        "groups": {
            "brain": [
                {
                    "name": "service-brain_timer",
                    "description": "Timer service",
                    "role": "service",
                    "status": "active",
                    "desired_state": "running",
                    "path": "/brain/infrastructure/service/timer"
                },
                {
                    "name": "agent-brain_dev",
                    "description": "Dev agent",
                    "role": "dev",
                    "status": "active",
                    "desired_state": "running",
                    "path": "/groups/brain/agent-brain_dev",
                    "tmux_session": "agent-brain_dev",
                    "required": True
                }
            ]
        },
        "group_meta": {
            "brain": {"type": "system", "description": "Brain system group"}
        }
    }


# ============== Proxy API Tests ==============

class TestProxyAPI:
    """Tests for Proxy API endpoints."""

    @patch('api.v2.proxy.httpx.AsyncClient')
    def test_get_proxy_stats_success(self, mock_client_class, mock_gateway_stats):
        """Test GET /api/v2/proxy/stats - success case."""
        mock_client = MagicMock()
        mock_client.__aenter__ = Mock(return_value=mock_client)
        mock_client.__aexit__ = Mock(return_value=None)
        mock_client.get = Mock(return_value=MagicMock(
            status_code=200,
            json=Mock(return_value=mock_gateway_stats),
            raise_for_status=Mock()
        ))
        mock_client_class.return_value = mock_client

        response = client.get("/api/v2/proxy/stats")

        assert response.status_code == 200
        data = response.json()
        assert "qps" in data
        assert "avg_latency_ms" in data
        assert data["qps"] == 42.5
        assert data["source"] == "brain_gateway"

    @patch('api.v2.proxy.httpx.AsyncClient')
    def test_get_proxy_stats_gateway_down(self, mock_client_class):
        """Test GET /api/v2/proxy/stats - gateway unavailable."""
        mock_client = MagicMock()
        mock_client.__aenter__ = Mock(return_value=mock_client)
        mock_client.__aexit__ = Mock(return_value=None)
        mock_client.get = Mock(side_effect=Exception("Connection refused"))
        mock_client_class.return_value = mock_client

        response = client.get("/api/v2/proxy/stats")

        assert response.status_code == 503

    @patch('api.v2.proxy.httpx.AsyncClient')
    def test_get_proxy_routes_success(self, mock_client_class, mock_gateway_routes):
        """Test GET /api/v2/proxy/routes - success case."""
        mock_client = MagicMock()
        mock_client.__aenter__ = Mock(return_value=mock_client)
        mock_client.__aexit__ = Mock(return_value=None)
        mock_client.get = Mock(return_value=MagicMock(
            status_code=200,
            json=Mock(return_value=mock_gateway_routes),
            raise_for_status=Mock()
        ))
        mock_client_class.return_value = mock_client

        response = client.get("/api/v2/proxy/routes")

        assert response.status_code == 200
        data = response.json()
        assert "routes" in data
        assert "platforms" in data["routes"]

    @patch('api.v2.proxy.httpx.AsyncClient')
    def test_get_proxy_traffic(self, mock_client_class, mock_gateway_stats):
        """Test GET /api/v2/proxy/traffic."""
        mock_client = MagicMock()
        mock_client.__aenter__ = Mock(return_value=mock_client)
        mock_client.__aexit__ = Mock(return_value=None)
        mock_client.get = Mock(return_value=MagicMock(
            status_code=200,
            json=Mock(return_value={"requests": 100, "errors": 2, "error_rate": 0.02}),
            raise_for_status=Mock()
        ))
        mock_client_class.return_value = mock_client

        response = client.get("/api/v2/proxy/traffic?minutes=5")

        assert response.status_code == 200
        data = response.json()
        assert "window_minutes" in data
        assert data["window_minutes"] == 5


# ============== Registry API Tests ==============

class TestRegistryAPI:
    """Tests for Registry API endpoints."""

    @patch('api.v2.registry.load_registry')
    def test_get_services(self, mock_load_registry, mock_registry_data):
        """Test GET /api/v2/registry/services."""
        mock_load_registry.return_value = mock_registry_data

        response = client.get("/api/v2/registry/services")

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert data["count"] >= 1
        assert data["services"][0]["name"].startswith("service-")

    @patch('api.v2.registry.load_registry')
    def test_get_agents(self, mock_load_registry, mock_registry_data):
        """Test GET /api/v2/registry/agents."""
        mock_load_registry.return_value = mock_registry_data

        response = client.get("/api/v2/registry/agents")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert data["count"] >= 1
        assert not data["agents"][0]["name"].startswith("service-")

    @patch('api.v2.registry.load_registry')
    def test_get_registry_health(self, mock_load_registry, mock_registry_data):
        """Test GET /api/v2/registry/health."""
        mock_load_registry.return_value = mock_registry_data

        response = client.get("/api/v2/registry/health")

        assert response.status_code == 200
        data = response.json()
        assert "total_agents" in data
        assert "active_count" in data
        assert "service_count" in data

    @patch('api.v2.registry.load_registry')
    def test_get_groups(self, mock_load_registry, mock_registry_data):
        """Test GET /api/v2/registry/groups."""
        mock_load_registry.return_value = mock_registry_data

        response = client.get("/api/v2/registry/groups")

        assert response.status_code == 200
        data = response.json()
        assert "groups" in data
        assert len(data["groups"]) >= 1

    @patch('api.v2.registry.load_registry')
    def test_registry_file_not_found(self, mock_load_registry):
        """Test registry endpoints when file not found."""
        from fastapi import HTTPException
        mock_load_registry.side_effect = HTTPException(status_code=503, detail="Registry file not found")

        response = client.get("/api/v2/registry/services")
        assert response.status_code == 503


# ============== Logs API Tests ==============

class TestLogsAPI:
    """Tests for Logs API endpoints."""

    def test_list_log_services(self):
        """Test GET /api/v2/logs/services."""
        response = client.get("/api/v2/logs/services")

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "count" in data

    def test_list_service_log_files(self):
        """Test GET /api/v2/logs/services/{service}/files."""
        response = client.get("/api/v2/logs/services/brain_timer/files")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "files" in data

    def test_websocket_log_stream_invalid_service(self):
        """Test WebSocket with invalid service name."""
        # WebSocket tests require async client, test via regular client
        # This tests the HTTP part (should fail as WebSocket required)
        response = client.get("/api/v2/logs/ws/invalid_service")
        # Should return method not allowed or upgrade required
        assert response.status_code in [404, 405]


# ============== App Tests ==============

class TestApp:
    """Tests for main app."""

    def test_root_endpoint(self):
        """Test GET /."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Agent Dashboard" in response.text

    def test_health_endpoint(self):
        """Test GET /health."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_v1_api_compatibility(self):
        """Test V1 API still works."""
        # These endpoints depend on initialized storage/collector
        # Just verify they exist
        response = client.get("/api/health")
        # May return 200 or 503 depending on daemon connection
        assert response.status_code in [200, 503]


# ============== Core Module Tests ==============

class TestLogReader:
    """Tests for LogReader module."""

    def test_log_reader_init(self):
        """Test LogReader initialization."""
        from core.log_reader import LogReader
        reader = LogReader()
        assert reader is not None
        assert not reader._running

    def test_log_buffer_init(self):
        """Test LogBuffer initialization."""
        from core.log_reader import LogBuffer
        import asyncio

        buffer = LogBuffer(max_lines=100)
        assert buffer.max_lines == 100
        assert len(buffer) == 0

    def test_log_reader_list_files(self):
        """Test LogReader.list_log_files."""
        from core.log_reader import LogReader
        reader = LogReader()
        files = reader.list_log_files()
        assert isinstance(files, list)


# ============== Performance/Load Tests ==============

class TestPerformance:
    """Basic performance tests."""

    @patch('api.v2.proxy.httpx.AsyncClient')
    def test_concurrent_requests(self, mock_client_class, mock_gateway_stats):
        """Test handling of concurrent requests."""
        mock_client = MagicMock()
        mock_client.__aenter__ = Mock(return_value=mock_client)
        mock_client.__aexit__ = Mock(return_value=None)
        mock_client.get = Mock(return_value=MagicMock(
            status_code=200,
            json=Mock(return_value=mock_gateway_stats),
            raise_for_status=Mock()
        ))
        mock_client_class.return_value = mock_client

        # Make multiple requests
        responses = []
        for _ in range(10):
            resp = client.get("/api/v2/proxy/stats")
            responses.append(resp.status_code)

        assert all(s == 200 for s in responses)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=api.v2", "--cov-report=term-missing"])
