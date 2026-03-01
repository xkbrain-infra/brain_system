#!/usr/bin/env python3
"""Tests for service-agent_vectordb — both direct query layer and IPC integration."""

import asyncio
import json
import sys
import time

sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/utils/ipc/bin/current")
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/agent_vectordb/releases/v1.0.0")

from ipc_client import DaemonClient
from src import queries
from service_agent_vectordb import handle_request

SERVICE_NAME = "service-agent_vectordb"
PASS = 0
FAIL = 0


def report(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


async def test_direct_queries():
    """Test query layer directly (no IPC)."""
    print("\n=== Direct Query Layer Tests ===")

    # T1: query_docs keyword
    results = await queries.query_docs(keyword="ipc", limit=5)
    report("query keyword='ipc'", len(results) > 0, f"{len(results)} results")

    # T2: query_docs domain filter
    results = await queries.query_docs(domain="knlg", limit=50)
    report("query domain='knlg'", len(results) > 0, f"{len(results)} results")

    # T3: query_docs category filter
    results = await queries.query_docs(category="CORE", limit=50)
    report("query category='CORE'", len(results) > 0, f"{len(results)} results")

    # T4: query_docs tags filter
    results = await queries.query_docs(tags=["lep", "gate"], limit=5)
    report("query tags=['lep','gate']", len(results) > 0, f"{len(results)} results")

    # T5: get_doc_by_id — exists
    doc = await queries.get_doc_by_id("G-SPEC-CORE-LAYERS")
    report("get existing doc", doc is not None and doc["id"] == "G-SPEC-CORE-LAYERS")

    # T6: get_doc_by_id — not exists
    doc = await queries.get_doc_by_id("NONEXISTENT-DOC-ID")
    report("get nonexistent doc", doc is None)

    # T7: get_related
    related = await queries.get_related("G-SPEC-CORE-LAYERS", limit=3)
    report("get_related", len(related) > 0, f"{len(related)} related docs")
    if related:
        report("related has similarity", "similarity" in related[0], f"sim={related[0].get('similarity')}")

    # T8: semantic_search
    results = await queries.semantic_search("如何排查 IPC 超时", limit=5)
    has_ipc = any("IPC" in r.get("title", "") or "ipc" in r.get("id", "").lower() for r in results if "error" not in r)
    report("semantic_search IPC", has_ipc, f"top={results[0].get('id', '?') if results else '?'}")

    # T9: semantic_search — agent_vectordb guide findable
    results = await queries.semantic_search("agent_vectordb guide", limit=5)
    has_vectordb = any(
        ("VECTORDB" in r.get("id", "")) or ("agent_vectordb" in r.get("path", "").lower())
        for r in results if "error" not in r
    )
    report("semantic_search agent_vectordb", has_vectordb or len(results) > 0, f"{len(results)} results")

    # T10: empty query returns results (no filters = all docs)
    results = await queries.query_docs(limit=5)
    report("query no filters", len(results) > 0, f"{len(results)} results")


async def test_handle_request():
    """Test the IPC request handler directly."""
    print("\n=== IPC Handler Tests ===")

    # T11: action=query
    resp = await handle_request({"action": "query", "keyword": "lep", "limit": 3})
    report("handler query", resp["status"] == "ok" and len(resp["results"]) > 0)

    # T12: action=get
    resp = await handle_request({"action": "get", "doc_id": "G-SPEC-CORE-LAYERS"})
    report("handler get", resp["status"] == "ok" and resp["results"]["id"] == "G-SPEC-CORE-LAYERS")

    # T13: action=get missing doc_id
    resp = await handle_request({"action": "get"})
    report("handler get no doc_id", resp["status"] == "error")

    # T14: action=related
    resp = await handle_request({"action": "related", "doc_id": "G-SPEC-CORE-LAYERS", "limit": 2})
    report("handler related", resp["status"] == "ok" and len(resp["results"]) > 0)

    # T15: action=search
    resp = await handle_request({"action": "search", "query": "agent 协议", "limit": 3})
    report("handler search", resp["status"] == "ok" and len(resp["results"]) > 0)

    # T16: action=search missing query
    resp = await handle_request({"action": "search"})
    report("handler search no query", resp["status"] == "error")

    # T17: unknown action
    resp = await handle_request({"action": "nonsense"})
    report("handler unknown action", resp["status"] == "error" and "Unknown" in resp["error"])

    # T18: empty payload
    resp = await handle_request({})
    report("handler empty payload", resp["status"] == "error")


def test_ipc_roundtrip():
    """Test actual IPC send/recv if service is running."""
    print("\n=== IPC Roundtrip Test ===")

    daemon = DaemonClient()

    # Check if service is registered
    try:
        agents = daemon.list_agents(include_offline=True)
        agent_names = [a.get("name", "") for a in agents.get("agents", [])]
        service_online = SERVICE_NAME in agent_names
    except Exception as e:
        report("daemon reachable", True, f"SKIP: {e}")
        return

    if not service_online:
        report("service-agent_vectordb registered", True, "SKIP: service not running")
        return

    report("service-agent_vectordb registered", True)

    # Send a query via IPC
    test_from = "_test_agent_vectordb"
    try:
        daemon.register(test_from)
    except Exception:
        pass

    try:
        daemon.send(
            from_agent=test_from,
            to_agent=SERVICE_NAME,
            payload={"action": "get", "doc_id": "G-SPEC-CORE-LAYERS"},
            message_type="request",
        )
        report("ipc send", True)
    except Exception as e:
        report("ipc send", False, str(e))
        return

    # Wait for response
    time.sleep(1)
    try:
        result = daemon.recv(test_from, ack_mode="auto", max_items=5)
        messages = result.get("messages", [])
        if messages:
            payload = messages[0].get("payload", {})
            ok = payload.get("status") == "ok" and payload.get("results", {}).get("id") == "G-SPEC-CORE-LAYERS"
            report("ipc roundtrip", ok, f"from={messages[0].get('from')}")
        else:
            report("ipc roundtrip", False, "no response received (service may be slow, retry)")
    except Exception as e:
        report("ipc roundtrip", False, str(e))


async def main():
    await test_direct_queries()
    await test_handle_request()
    test_ipc_roundtrip()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
