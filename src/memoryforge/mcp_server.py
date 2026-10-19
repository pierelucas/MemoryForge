from __future__ import annotations

import json
import os

from mcp.server.mcpserver import MCPServer

from memoryforge import __version__
from memoryforge.scope import detect_scope, normalize_scope
from memoryforge.service import get_service


def build_mcp() -> MCPServer:
    mcp = MCPServer(
        "MemoryForge",
        instructions=(
            "Durable local memory. Call memory_brief at the start of a session. "
            "Call memory_add when you learn a preference, decision, convention, or debug lesson "
            "that should survive this session. Do not store secrets or ephemeral task state. "
            "Pass scope as 'global' or 'project:host/owner/repo'."
        ),
        version=__version__,
    )

    @mcp.tool(description="Search durable memories by meaning and keywords.")
    def memory_search(query: str, scope: str | None = None, limit: int = 8) -> str:
        """Search durable memories by meaning and keywords.

        scope: 'global' or 'project:host/owner/repo'. Project searches also include global.
        """
        resolved = _scope_or_detect(scope)
        rows = get_service().search(query, scope=resolved, limit=max(1, min(limit, 30)))
        return _dump({"scope": resolved or "all", "memories": [_public(row) for row in rows]})

    @mcp.tool(description="Store a durable fact. Raw session text is distilled only if an LLM is enabled.")
    def memory_add(text: str, scope: str | None = None, source: str | None = None) -> str:
        """Save text into long-term memory.

        Pass scope 'global' for user preferences and 'project:host/owner/repo' for the repository.
        If scope is omitted, a local stdio session uses the git remote of the working directory.
        """
        resolved = _scope_or_detect(scope)
        result = get_service().add(text, scope=resolved, source=source or "mcp", detect=False)
        return _dump(
            {
                "scope": resolved or "global",
                "noop": result["noop"],
                "llm": result["llm"],
                "warning": result.get("warning"),
                "memories": [_public(row) for row in result["memories"]],
            }
        )

    @mcp.tool(description="List active memories, newest first.")
    def memory_list(scope: str | None = None, limit: int = 50) -> str:
        """List memories. Without scope, list everything active."""
        resolved = normalize_scope(scope) if scope else ""
        rows = get_service().list_memories(resolved or None, limit=max(1, min(limit, 200)))
        return _dump({"memories": [_public(row) for row in rows]})

    @mcp.tool(description="Forget one memory by id.")
    def memory_forget(memory_id: str) -> str:
        """Soft-delete a memory so it no longer appears in search."""
        get_service().forget(memory_id.strip())
        return _dump({"forgotten": memory_id.strip()})

    @mcp.tool(description="Pin or unpin a memory so it stays in the session brief.")
    def memory_pin(memory_id: str, pinned: bool = True) -> str:
        """Pin a memory (or unpin it when pinned is false)."""
        row = get_service().pin(memory_id.strip(), pinned)
        return _dump(_public(row))

    @mcp.tool(description="Compact session-start card: pinned memories plus recent ones.")
    def memory_brief(scope: str | None = None) -> str:
        """Return the memories an agent should read before working.

        Pass the project scope when you know the git remote. Otherwise the working directory is used.
        """
        resolved = _scope_or_detect(scope)
        card = get_service().brief(resolved or None, detect=False)
        return _dump(
            {
                "scope": card["scope"],
                "memories": [_public(row) for row in card["memories"]],
            }
        )

    return mcp


def _scope_or_detect(scope: str | None) -> str:
    if scope and scope.strip():
        return normalize_scope(scope)
    if os.environ.get("MEMORYFORGE_MCP_DETECT", "1") != "0":
        return detect_scope()
    return "global"


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "scope": row["scope"],
        "text": row["text"],
        "kind": row["kind"],
        "pinned": row["pinned"],
        "source": row.get("source"),
        "score": row.get("score"),
        "updated_at": row["updated_at"],
    }


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
