import asyncio

from fastapi.testclient import TestClient

from memoryforge.mcp_server import build_mcp
from memoryforge.server import create_app


def test_mcp_exposes_the_six_tools():
    mcp = build_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "memory_search",
        "memory_add",
        "memory_list",
        "memory_forget",
        "memory_pin",
        "memory_brief",
    }


def test_mcp_http_does_not_redirect(monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_BIND_HOST", "0.0.0.0")
    app = create_app()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=body,
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code != 307
    assert response.status_code < 500
