#!/usr/bin/env python3
"""Bridge between a Unix socket and a TCP endpoint.

This is used by sandbox bootstrap to expose the host brain_ipc Unix socket to
containers where direct Unix socket bind mounts are unreliable.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Callable


BUFFER_SIZE = 64 * 1024
MAX_ACTIVE_BRIDGES = 128
LOG_THROTTLE_WINDOW_S = 5.0
_SHUTDOWN = threading.Event()
_ACTIVE_BRIDGE_SLOTS = threading.BoundedSemaphore(MAX_ACTIVE_BRIDGES)
_LOG_THROTTLE_LOCK = threading.Lock()
_LOG_THROTTLE_STATE: dict[tuple[str, str], dict[str, float | int]] = {}


def _configure_logging(log_file: str | None) -> None:
    kwargs = {
        "level": logging.INFO,
        "format": "%(asctime)s %(levelname)s %(message)s",
    }
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        kwargs["filename"] = log_file
    else:
        kwargs["stream"] = sys.stderr
    logging.basicConfig(**kwargs)


def _write_pid(pid_file: str | None) -> None:
    if not pid_file:
        return
    path = Path(pid_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def _cleanup() -> None:
        try:
            if path.exists():
                current = path.read_text(encoding="utf-8").strip()
                if current == str(os.getpid()):
                    path.unlink()
        except Exception:
            pass

    atexit.register(_cleanup)


def _install_signal_handlers() -> None:
    def _handle(_signum: int, _frame: object) -> None:
        _SHUTDOWN.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _connect_unix(path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    return sock


def _default_gateway_ip() -> str | None:
    route_path = Path("/proc/net/route")
    if not route_path.exists():
        return None

    try:
        for line in route_path.read_text(encoding="utf-8").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[1] != "00000000":
                continue
            flags = int(fields[3], 16)
            if not (flags & 0x2):
                continue
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except Exception:
        return None
    return None


def _tcp_target_candidates(host: str) -> list[str]:
    candidates = [host]
    if host != "host.docker.internal":
        return candidates

    env_host = (os.environ.get("HOST_IP") or "").strip()
    gateway_host = _default_gateway_ip()
    for candidate in (env_host, gateway_host):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _connect_tcp(host: str, port: int) -> socket.socket:
    last_error: OSError | None = None
    for candidate in _tcp_target_candidates(host):
        try:
            return socket.create_connection((candidate, port), timeout=5)
        except OSError as exc:
            last_error = exc

    if last_error is None:
        raise OSError(f"no TCP target candidates for {host}:{port}")
    raise last_error


def _close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


def _log_throttled_warning(label: str, detail: str) -> None:
    key = (label, detail)
    now = time.monotonic()

    with _LOG_THROTTLE_LOCK:
        state = _LOG_THROTTLE_STATE.get(key)
        if state is None:
            _LOG_THROTTLE_STATE[key] = {"last_logged": now, "suppressed": 0}
            logging.warning("%s: %s", label, detail)
            return

        last_logged = float(state["last_logged"])
        if now - last_logged < LOG_THROTTLE_WINDOW_S:
            state["suppressed"] = int(state["suppressed"]) + 1
            return

        suppressed = int(state["suppressed"])
        state["last_logged"] = now
        state["suppressed"] = 0

    if suppressed:
        logging.warning("%s: %s (suppressed %d similar events)", label, detail, suppressed)
    else:
        logging.warning("%s: %s", label, detail)


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while not _SHUTDOWN.is_set():
            data = src.recv(BUFFER_SIZE)
            if not data:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                break
            dst.sendall(data)
    except OSError:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _bridge_pair(
    client: socket.socket,
    upstream_factory: Callable[[], socket.socket],
    label: str,
    slots: threading.BoundedSemaphore,
) -> None:
    upstream: socket.socket | None = None
    try:
        upstream = upstream_factory()
        thread = threading.Thread(target=_pump, args=(client, upstream), daemon=True)
        thread.start()
        _pump(upstream, client)
        thread.join(timeout=1)
    except Exception as exc:
        _log_throttled_warning(label, f"bridge pair failed: {exc}")
    finally:
        _close_socket(client)
        _close_socket(upstream)
        slots.release()


def _bind_unix_listener(path: str, socket_mode: int) -> socket.socket:
    listen_path = Path(path)
    listen_path.parent.mkdir(parents=True, exist_ok=True)
    if listen_path.exists() or listen_path.is_symlink():
        listen_path.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    os.chmod(path, socket_mode)
    sock.listen(64)
    sock.settimeout(1.0)

    def _cleanup() -> None:
        try:
            sock.close()
        except OSError:
            pass
        try:
            if listen_path.exists() or listen_path.is_symlink():
                listen_path.unlink()
        except OSError:
            pass

    atexit.register(_cleanup)
    return sock


def _bind_tcp_listener(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(64)
    sock.settimeout(1.0)
    atexit.register(lambda: sock.close())
    return sock


def _dispatch_client(
    client: socket.socket,
    upstream_factory: Callable[[], socket.socket],
    label: str,
    slots: threading.BoundedSemaphore = _ACTIVE_BRIDGE_SLOTS,
) -> bool:
    if not slots.acquire(blocking=False):
        _log_throttled_warning(label, "bridge saturated; dropping connection")
        _close_socket(client)
        return False

    try:
        thread = threading.Thread(
            target=_bridge_pair,
            args=(client, upstream_factory, label, slots),
            daemon=True,
        )
        thread.start()
        return True
    except Exception as exc:
        slots.release()
        _close_socket(client)
        _log_throttled_warning(label, f"failed to start bridge thread: {exc}")
        return False


def _serve(listener: socket.socket, upstream_factory: Callable[[], socket.socket], label: str) -> None:
    logging.info("%s bridge ready", label)
    while not _SHUTDOWN.is_set():
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            if _SHUTDOWN.is_set():
                break
            raise
        _dispatch_client(client, upstream_factory, label)


def _parse_socket_mode(raw: str) -> int:
    return int(raw, 8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Unix/TCP socket bridge")
    parser.add_argument("--log-file", help="Optional log file path")
    parser.add_argument("--pid-file", help="Optional pid file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tcp_parser = subparsers.add_parser("tcp-listen", help="Listen on TCP and relay to a Unix socket")
    tcp_parser.add_argument("--listen-host", default="0.0.0.0")
    tcp_parser.add_argument("--listen-port", type=int, required=True)
    tcp_parser.add_argument("--target-unix", required=True)

    unix_parser = subparsers.add_parser("unix-listen", help="Listen on a Unix socket and relay to TCP")
    unix_parser.add_argument("--listen-unix", required=True)
    unix_parser.add_argument("--target-host", required=True)
    unix_parser.add_argument("--target-port", type=int, required=True)
    unix_parser.add_argument("--socket-mode", default="666", type=_parse_socket_mode)

    args = parser.parse_args()
    _configure_logging(args.log_file)
    _write_pid(args.pid_file)
    _install_signal_handlers()

    if args.command == "tcp-listen":
        listener = _bind_tcp_listener(args.listen_host, args.listen_port)
        _serve(
            listener,
            lambda: _connect_unix(args.target_unix),
            f"tcp:{args.listen_host}:{args.listen_port} -> unix:{args.target_unix}",
        )
        return 0

    listener = _bind_unix_listener(args.listen_unix, args.socket_mode)
    _serve(
        listener,
        lambda: _connect_tcp(args.target_host, args.target_port),
        f"unix:{args.listen_unix} -> tcp:{args.target_host}:{args.target_port}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
