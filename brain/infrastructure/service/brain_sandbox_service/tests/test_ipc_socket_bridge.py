from __future__ import annotations

import importlib.util
import socket
import threading
from pathlib import Path


MODULE_PATH = Path("/xkagent_infra/brain/infrastructure/service/brain_sandbox_service/current/ipc_socket_bridge.py")
SPEC = importlib.util.spec_from_file_location("ipc_socket_bridge_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bridge_pair_throttles_repeated_failures(monkeypatch):
    warnings: list[str] = []
    times = iter([0.0, 1.0, 6.5])

    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(MODULE.logging, "warning", lambda msg, *args: warnings.append(msg % args))
    monkeypatch.setattr(MODULE, "_LOG_THROTTLE_STATE", {})

    for _ in range(3):
        client, peer = socket.socketpair()
        slots = threading.BoundedSemaphore(1)
        assert slots.acquire(blocking=False)
        try:
            MODULE._bridge_pair(
                client,
                lambda: (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory")),
                "test-bridge",
                slots,
            )
        finally:
            peer.close()

    assert warnings == [
        "test-bridge: bridge pair failed: [Errno 2] No such file or directory",
        "test-bridge: bridge pair failed: [Errno 2] No such file or directory (suppressed 1 similar events)",
    ]


def test_dispatch_client_drops_connection_when_bridge_slots_are_exhausted(monkeypatch):
    warnings: list[str] = []
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)

    monkeypatch.setattr(MODULE.logging, "warning", lambda msg, *args: warnings.append(msg % args))
    monkeypatch.setattr(MODULE, "_LOG_THROTTLE_STATE", {})
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: 0.0)

    client, peer = socket.socketpair()
    try:
        assert not MODULE._dispatch_client(client, lambda: peer, "test-bridge", slots)
        assert peer.recv(1) == b""
    finally:
        peer.close()
        slots.release()

    assert warnings == ["test-bridge: bridge saturated; dropping connection"]


def test_connect_tcp_falls_back_to_host_ip_when_host_docker_internal_is_missing(monkeypatch):
    calls: list[tuple[str, int]] = []
    sentinel = object()

    def fake_create_connection(address: tuple[str, int], timeout: float):
        calls.append(address)
        if address[0] == "host.docker.internal":
            raise socket.gaierror(-2, "Name or service not known")
        if address[0] == "10.20.33.183":
            return sentinel
        raise AssertionError(f"unexpected address: {address}, timeout={timeout}")

    monkeypatch.setenv("HOST_IP", "10.20.33.183")
    monkeypatch.setattr(MODULE, "_default_gateway_ip", lambda: None)
    monkeypatch.setattr(MODULE.socket, "create_connection", fake_create_connection)

    sock = MODULE._connect_tcp("host.docker.internal", 9800)

    assert sock is sentinel
    assert calls == [
        ("host.docker.internal", 9800),
        ("10.20.33.183", 9800),
    ]
