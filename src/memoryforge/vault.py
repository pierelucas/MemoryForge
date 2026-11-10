"""Readable Markdown projection of the SQLite memory.

The database stays the source of truth for search, MCP, and backups.
These files are rewritten so a person can read the same layers other
agents keep as Markdown: USER.md, MEMORY.md, daily notes, and DREAMS.md.
Editing a file does not change memory. The notebook rewrites it.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from memoryforge.db import Store
from memoryforge.paths import data_dir, vault_dir

_KIND_HEADING = {
    "decision": "Decisions",
    "convention": "Conventions",
    "fact": "Facts",
    "debug": "Lessons",
}
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def scope_dir(scope: str) -> Path:
    """Directory for one scope. `..` and absolute parts cannot escape the vault."""
    root = _vault_root()
    parts = _scope_parts(scope)
    path = root.joinpath(*parts)
    resolved = path.resolve()
    resolved.relative_to(root)
    return resolved


def vault_files(scope: str) -> dict[str, str]:
    base = scope_dir(scope)
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "identity": str(base / "IDENTITY.md"),
        "soul": str(base / "SOUL.md"),
        "user": str(base / "USER.md"),
        "memory": str(base / "MEMORY.md"),
        "dreams": str(base / "DREAMS.md"),
        "today": str(base / "memory" / f"{today}.md"),
    }


def write_scopes(store: Store, scopes: list[str] | None = None) -> None:
    chosen = list(scopes) if scopes is not None else _known_scopes(store)
    seen: list[str] = []
    for scope in chosen:
        if scope and scope not in seen:
            seen.append(scope)
            write_scope(store, scope)
    write_index(store)


def write_scope(store: Store, scope: str) -> None:
    if not scope:
        return
    base = scope_dir(scope)
    base.mkdir(parents=True, exist_ok=True)
    rows = store.all_active(scope)
    durable = [row for row in rows if (row.get("tier") or "durable") != "daily"]
    daily = [row for row in rows if row.get("tier") == "daily"]
    preferences = [row for row in durable if row.get("kind") == "preference"]
    curated = [row for row in durable if row.get("kind") != "preference"]
    persona = store.personas_in([scope]).get(scope) or {"identity": "", "soul": ""}
    _write(base / "IDENTITY.md", _identity_md(scope, persona.get("identity") or ""))
    _write(base / "SOUL.md", _soul_md(scope, persona.get("soul") or ""))
    _write(base / "USER.md", _user_md(scope, preferences))
    _write(base / "MEMORY.md", _memory_md(scope, curated))
    _write(base / "DREAMS.md", _dreams_md(scope, store.list_dreams(scope, limit=40)))
    memory_dir = base / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[dict]] = {}
    for row in daily:
        by_day.setdefault(_day(row.get("created_at")), []).append(row)
    for day, notes in by_day.items():
        _write(memory_dir / f"{day}.md", _daily_md(day, notes))
    for child in memory_dir.glob("*.md"):
        if child.stem not in by_day:
            child.unlink()
    if not by_day:
        try:
            memory_dir.rmdir()
        except OSError:
            pass


def write_index(store: Store) -> None:
    root = _vault_root()
    root.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MemoryForge",
        "",
        "Readable projection of the local database. Search still uses SQLite.",
        "Editing these files does not change memory. The notebook rewrites them.",
        "",
        "| Scope | Durable | Daily |",
        "|---|---:|---:|",
    ]
    scopes = store.scopes()
    if not scopes:
        lines.append("| — | 0 | 0 |")
    for item in scopes:
        counts = store.tier_counts(item["scope"])
        label = item["scope"]
        lines.append(f"| `{label}` | {counts.get('durable', 0)} | {counts.get('daily', 0)} |")
    lines.append("")
    _write(root / "INDEX.md", "\n".join(lines))


def rebuild(store: Store) -> Path:
    """Replace the vault so it matches the database, including after a restore."""
    root = _vault_root()
    data = data_dir().resolve()
    if root.exists() or root.is_symlink():
        resolved = root.resolve()
        if resolved.parent != data or resolved.name != "vault":
            raise OSError("Refusing to replace a vault outside the data directory.")
        shutil.rmtree(resolved)
    write_scopes(store, None)
    return root


def read_projection(scope: str, key: str) -> tuple[str, str]:
    """Return (display name, text) for a known file. Rejects arbitrary paths."""
    base = scope_dir(scope)
    if key == "identity":
        path, name = base / "IDENTITY.md", "IDENTITY.md"
    elif key == "soul":
        path, name = base / "SOUL.md", "SOUL.md"
    elif key == "user":
        path, name = base / "USER.md", "USER.md"
    elif key == "memory":
        path, name = base / "MEMORY.md", "MEMORY.md"
    elif key == "dreams":
        path, name = base / "DREAMS.md", "DREAMS.md"
    elif key == "index":
        path, name = _vault_root() / "INDEX.md", "INDEX.md"
    elif key.startswith("day:"):
        day = key.split(":", 1)[1]
        if not _DAY.fullmatch(day):
            raise ValueError("Unknown file.")
        path, name = base / "memory" / f"{day}.md", f"memory/{day}.md"
    else:
        raise ValueError("Unknown file.")
    if key != "index":
        path.resolve().relative_to(base.resolve() if base.exists() else scope_dir(scope))
    if not path.is_file():
        return name, ""
    return name, path.read_text(encoding="utf-8")


def list_projection(scope: str) -> list[dict]:
    base = scope_dir(scope)
    files = [
        {"key": "identity", "name": "IDENTITY.md"},
        {"key": "soul", "name": "SOUL.md"},
        {"key": "user", "name": "USER.md"},
        {"key": "memory", "name": "MEMORY.md"},
        {"key": "dreams", "name": "DREAMS.md"},
    ]
    memory_dir = base / "memory"
    if memory_dir.is_dir():
        for path in sorted(memory_dir.glob("*.md"), reverse=True):
            if _DAY.fullmatch(path.stem):
                files.append({"key": f"day:{path.stem}", "name": f"memory/{path.name}"})
    return files


def render_preview(text: str) -> str:
    """Escape and lightly structure our own Markdown. Not a general renderer."""
    from html import escape

    blocks: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
            items.clear()

    for raw in text.splitlines():
        line = re.sub(r"<!--.*?-->", "", raw).rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("# "):
            flush()
            blocks.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            flush()
            blocks.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            items.append(escape(line[2:].strip()))
        elif line.startswith("  ") and items:
            items[-1] += "<br>" + escape(line.strip())
        else:
            flush()
            blocks.append(f"<p>{escape(line.strip())}</p>")
    flush()
    return "\n".join(blocks)


def _vault_root() -> Path:
    path = vault_dir()
    if path.is_symlink():
        raise OSError("Vault path is a symlink.")
    root = path.resolve()
    data = data_dir().resolve()
    if root.parent != data or root.name != "vault":
        raise OSError("Vault path escaped the data directory.")
    return root


def _scope_parts(scope: str) -> list[str]:
    if scope == "global":
        return ["global"]
    if scope.startswith("project:"):
        rest = scope.split(":", 1)[1]
        parts = [part for part in rest.split("/") if part not in {"", ".", ".."}]
        return ["project", *(parts or ["unknown"])]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", scope).strip("-") or "scope"
    return ["other", slug]


def _known_scopes(store: Store) -> list[str]:
    found = [row["scope"] for row in store.scopes()]
    for scope in store.dream_scopes() + store.persona_scopes():
        if scope not in found:
            found.append(scope)
    return found


def _identity_md(scope: str, text: str) -> str:
    lines = [
        "# IDENTITY",
        "",
        "Who the agent is in this scope. Evergreen. Not a fact log.",
        f"Scope: `{scope}`",
        "",
    ]
    if text.strip():
        lines.append(text.strip())
    else:
        lines.append("_Unset._")
    lines.append("")
    return "\n".join(lines)


def _soul_md(scope: str, text: str) -> str:
    lines = [
        "# SOUL",
        "",
        "Voice, stance, and boundaries. Evergreen. Not a transcript.",
        "If this scope is a project, global voice still applies. Project wins on conflict.",
        f"Scope: `{scope}`",
        "",
    ]
    if text.strip():
        lines.append(text.strip())
    else:
        lines.append("_Unset._")
    lines.append("")
    return "\n".join(lines)


def _user_md(scope: str, rows: list[dict]) -> str:
    lines = [
        "# USER",
        "",
        "Preferences as directives. Evergreen. Not a transcript.",
        f"Scope: `{scope}`",
        "",
    ]
    if not rows:
        lines.append("_No preferences in this scope._")
        lines.append("")
        return "\n".join(lines)
    for row in rows:
        lines.extend(_bullet(row))
    return "\n".join(lines)


def _memory_md(scope: str, rows: list[dict]) -> str:
    lines = [
        "# MEMORY",
        "",
        "Curated durable facts. Evergreen. Not a daily log.",
        f"Scope: `{scope}`",
        "",
    ]
    if not rows:
        lines.append("_No durable facts in this scope._")
        lines.append("")
        return "\n".join(lines)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("kind") or "fact", []).append(row)
    for kind in ("decision", "convention", "fact", "debug"):
        group = grouped.get(kind) or []
        if not group:
            continue
        lines.append(f"## {_KIND_HEADING[kind]}")
        lines.append("")
        for row in group:
            lines.extend(_bullet(row))
    return "\n".join(lines)


def _daily_md(day: str, rows: list[dict]) -> str:
    lines = [
        f"# {day}",
        "",
        "Working notes. These decay in search. Dreaming may promote a note verbatim; it does not invent one.",
        "",
    ]
    for row in rows:
        lines.extend(_bullet(row))
    return "\n".join(lines)


def _dreams_md(scope: str, dreams: list[dict]) -> str:
    lines = [
        "# DREAMS",
        "",
        "Review only. Not injected at session start and not a memory.",
        f"Scope: `{scope}`",
        "",
    ]
    if not dreams:
        lines.append("_No sweep yet._")
        lines.append("")
        return "\n".join(lines)
    for dream in dreams:
        when = (dream.get("created_at") or "")[:16].replace("T", " ")
        lines.append(f"## {when} · {dream.get('phase') or 'sweep'}")
        lines.append("")
        lines.append(dream.get("summary") or "")
        lines.append("")
    return "\n".join(lines)


def _bullet(row: dict) -> list[str]:
    text = (row.get("text") or "").strip()
    comment = (
        f"<!-- id:{row.get('id')} tier:{row.get('tier') or 'durable'} "
        f"kind:{row.get('kind') or 'fact'} recalls:{int(row.get('recalls') or 0)} "
        f"pinned:{1 if row.get('pinned') else 0} -->"
    )
    body = text.splitlines() or [""]
    lines = [f"- {body[0]}"]
    lines.extend(f"  {extra}" for extra in body[1:])
    lines.append(f"  {comment}")
    lines.append("")
    return lines


def _day(value: str | None) -> str:
    text = (value or "")[:10]
    if _DAY.fullmatch(text):
        return text
    return datetime.now(timezone.utc).date().isoformat()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
