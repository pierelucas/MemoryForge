from __future__ import annotations

import math
import os
import re
import sqlite3
import struct
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB,
    kind TEXT NOT NULL DEFAULT 'fact',
    source TEXT,
    confidence REAL NOT NULL DEFAULT 1,
    pinned INTEGER NOT NULL DEFAULT 0,
    forgotten INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    tier TEXT NOT NULL DEFAULT 'durable',
    recalls INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT,
    importance INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(forgotten, superseded_by);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, scope, kind,
    content='memories',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, scope, kind)
    VALUES (new.id, new.text, new.scope, new.kind);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, scope, kind)
    VALUES ('delete', old.id, old.text, old.scope, old.kind);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, scope, kind)
    VALUES ('delete', old.id, old.text, old.scope, old.kind);
    INSERT INTO memories_fts(rowid, text, scope, kind)
    VALUES (new.id, new.text, new.scope, new.kind);
END;

CREATE TABLE IF NOT EXISTS dreams (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    phase TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dreams_scope ON dreams(scope, created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pack_vec(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def unpack_vec(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    count = len(blob) // 4
    if count == 0:
        return None
    return list(struct.unpack(f"{count}f", blob[: count * 4]))


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def clamp_limit(limit: int, maximum: int = 200) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 50
    return max(1, min(value, maximum))


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate_columns()
        try:
            # SQLite creates the file with the process umask. Memory may
            # contain personal facts, so keep it private like the config.
            os.chmod(path, 0o600)
        except OSError:
            pass
        self._migrate_scopes()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def insert(
        self,
        *,
        text: str,
        scope: str,
        kind: str,
        source: str | None,
        embedding: list[float] | None,
        confidence: float = 1.0,
        pinned: bool = False,
        tier: str = "durable",
        importance: int | None = None,
    ) -> dict:
        now = utc_now()
        memory_id = uuid.uuid4().hex
        stored_tier = tier if tier in {"daily", "durable"} else "durable"
        stored_importance = importance if importance is not None else _importance_for(kind)
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO memories (
                    uuid, scope, text, embedding, kind, source, confidence,
                    pinned, forgotten, superseded_by, tier, recalls, last_recalled_at,
                    importance, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, 0, NULL, ?, ?, ?)
                """,
                (
                    memory_id,
                    scope,
                    text,
                    pack_vec(embedding) if embedding else None,
                    kind,
                    source,
                    confidence,
                    1 if pinned else 0,
                    stored_tier,
                    max(1, min(10, int(stored_importance))),
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row_id = cur.lastrowid
        return self._by_rowid(row_id)

    def _by_rowid(self, row_id: int) -> dict:
        with self._lock:
            row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(row_id)
        return row_to_dict(row)

    def get(self, memory_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM memories WHERE uuid = ?", (memory_id,)).fetchone()
        return row_to_dict(row) if row else None

    def find_exact(self, scope: str, text: str) -> dict | None:
        # SQLite's lower() only folds ASCII, which breaks German umlauts.
        needle = text.strip().casefold()
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM memories
                WHERE scope = ? AND forgotten = 0 AND superseded_by IS NULL
                ORDER BY id DESC
                """,
                (scope,),
            ).fetchall()
        for row in rows:
            if row["text"].strip().casefold() == needle:
                return row_to_dict(row)
        return None

    def update_text(
        self,
        memory_id: str,
        text: str,
        embedding: list[float] | None,
        kind: str | None = None,
        scope: str | None = None,
    ) -> dict:
        current = self.get(memory_id)
        if current is None:
            raise KeyError(memory_id)
        with self._lock:
            self.conn.execute(
                """
                UPDATE memories
                SET text = ?, embedding = ?, kind = ?, scope = ?, updated_at = ?
                WHERE uuid = ?
                """,
                (
                    text,
                    pack_vec(embedding) if embedding else None,
                    kind or current["kind"],
                    scope or current["scope"],
                    utc_now(),
                    memory_id,
                ),
            )
            self.conn.commit()
        found = self.get(memory_id)
        if found is None:
            raise KeyError(memory_id)
        return found

    def set_tier(self, memory_id: str, tier: str) -> None:
        if tier not in {"daily", "durable"}:
            raise ValueError(tier)
        if self.get(memory_id) is None:
            raise KeyError(memory_id)
        with self._lock:
            self.conn.execute(
                "UPDATE memories SET tier = ?, updated_at = ? WHERE uuid = ?",
                (tier, utc_now(), memory_id),
            )
            self.conn.commit()

    def note_recalls(self, ids: list[str]) -> None:
        """Count an explicit search hit. Does not touch updated_at, so decay stays honest."""
        if not ids:
            return
        now = utc_now()
        with self._lock:
            for start in range(0, len(ids), 500):
                chunk = [memory_id for memory_id in ids[start : start + 500] if memory_id]
                if not chunk:
                    continue
                marks = ",".join("?" for _ in chunk)
                self.conn.execute(
                    f"""
                    UPDATE memories
                    SET recalls = recalls + 1, last_recalled_at = ?
                    WHERE uuid IN ({marks}) AND forgotten = 0 AND superseded_by IS NULL
                    """,
                    [now, *chunk],
                )
            self.conn.commit()

    def set_kind(self, memory_id: str, kind: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE memories SET kind = ? WHERE uuid = ?",
                (kind, memory_id),
            )
            self.conn.commit()

    def set_embedding(self, memory_id: str, embedding: list[float]) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE memories SET embedding = ? WHERE uuid = ?",
                (pack_vec(embedding), memory_id),
            )
            self.conn.commit()

    def set_pinned(self, memory_id: str, pinned: bool) -> dict:
        if self.get(memory_id) is None:
            raise KeyError(memory_id)
        with self._lock:
            self.conn.execute(
                "UPDATE memories SET pinned = ?, updated_at = ? WHERE uuid = ?",
                (1 if pinned else 0, utc_now(), memory_id),
            )
            self.conn.commit()
        found = self.get(memory_id)
        if found is None:
            raise KeyError(memory_id)
        return found

    def forget(self, memory_id: str) -> None:
        if self.get(memory_id) is None:
            raise KeyError(memory_id)
        with self._lock:
            self.conn.execute(
                "UPDATE memories SET forgotten = 1, pinned = 0, updated_at = ? WHERE uuid = ?",
                (utc_now(), memory_id),
            )
            self.conn.commit()

    def forget_scope(self, scope: str) -> int:
        """Hide every active row in a scope. Returns how many rows changed."""
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE memories
                SET forgotten = 1, pinned = 0, updated_at = ?
                WHERE scope = ? AND forgotten = 0 AND superseded_by IS NULL
                """,
                (utc_now(), scope),
            )
            self.conn.commit()
            return cur.rowcount

    def supersede(self, old_ids: list[str], new_id: str, *, scope: str | None = None) -> int:
        """Mark old rows as replaced. Returns how many rows actually changed.

        With a scope, ids from another scope are left alone so one repository
        can never retire a fact that belongs somewhere else.
        """
        now = utc_now()
        updated = 0
        with self._lock:
            for old_id in old_ids:
                if not isinstance(old_id, str) or not old_id or old_id == new_id:
                    continue
                sql = """
                    UPDATE memories
                    SET superseded_by = ?, pinned = 0, updated_at = ?
                    WHERE uuid = ? AND uuid != ?
                      AND forgotten = 0 AND superseded_by IS NULL
                """
                params: list = [new_id, now, old_id, new_id]
                if scope:
                    sql += " AND scope = ?"
                    params.append(scope)
                updated += self.conn.execute(sql, params).rowcount
            self.conn.commit()
        return updated

    def list_memories(
        self,
        *,
        scope: str | None = None,
        include_global: bool = False,
        limit: int = 50,
        pinned_only: bool = False,
        tier: str | None = None,
        kind: str | None = None,
    ) -> list[dict]:
        where, params = _active_scope(scope, include_global)
        if pinned_only:
            where += " AND pinned = 1"
        if tier in {"daily", "durable"}:
            where += " AND tier = ?"
            params.append(tier)
        if kind:
            where += " AND kind = ?"
            params.append(kind)
        params.append(clamp_limit(limit))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY pinned DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def all_active(self, scope: str | None = None) -> list[dict]:
        """Every active row in a scope, for dream and reembed. No page limit."""
        where, params = _active_scope(scope, include_global=False)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM memories WHERE {where} ORDER BY id",
                params,
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def scopes(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT scope, COUNT(*) AS n
                FROM memories
                WHERE forgotten = 0 AND superseded_by IS NULL
                GROUP BY scope
                ORDER BY CASE WHEN scope = 'global' THEN 0 ELSE 1 END, scope
                """
            ).fetchall()
        return [{"scope": row["scope"], "count": row["n"]} for row in rows]

    def tier_counts(self, scope: str | None = None) -> dict[str, int]:
        where, params = _active_scope(scope, include_global=False)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT tier, COUNT(*) AS n FROM memories WHERE {where} GROUP BY tier",
                params,
            ).fetchall()
        counts = {"durable": 0, "daily": 0}
        for row in rows:
            counts[str(row["tier"])] = int(row["n"])
        return counts

    def list_recent_daily(
        self,
        *,
        scope: str | None,
        include_global: bool,
        since: str,
        limit: int = 8,
    ) -> list[dict]:
        where, params = _active_scope(scope, include_global)
        where += " AND tier = 'daily' AND created_at >= ?"
        params.extend([since, clamp_limit(limit)])
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def insert_dream(self, scope: str, phase: str, summary: str) -> dict:
        now = utc_now()
        dream_id = uuid.uuid4().hex
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO dreams (uuid, scope, phase, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (dream_id, scope, phase, summary, now),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM dreams WHERE uuid = ?", (dream_id,)).fetchone()
        return _dream_to_dict(row)

    def list_dreams(self, scope: str | None = None, limit: int = 40) -> list[dict]:
        params: list = []
        where = "1 = 1"
        if scope and scope not in {"", "all"}:
            where = "scope = ?"
            params.append(scope)
        params.append(clamp_limit(limit, 200))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM dreams WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_dream_to_dict(row) for row in rows]

    def dream_scopes(self) -> list[str]:
        with self._lock:
            rows = self.conn.execute("SELECT DISTINCT scope FROM dreams ORDER BY scope").fetchall()
        return [row["scope"] for row in rows]

    def count_active(self) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE forgotten = 0 AND superseded_by IS NULL"
            ).fetchone()
        return int(row["n"]) if row else 0

    def all_for_reembed(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT uuid, text FROM memories WHERE forgotten = 0"
            ).fetchall()
        return [{"id": row["uuid"], "text": row["text"]} for row in rows]

    def vectors_for(self, scope: str | None, include_global: bool) -> list[tuple[str, list[float]]]:
        where, params = _active_scope(scope, include_global)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT uuid, embedding FROM memories WHERE {where} AND embedding IS NOT NULL",
                params,
            ).fetchall()
        found: list[tuple[str, list[float]]] = []
        for row in rows:
            vec = unpack_vec(row["embedding"])
            if vec:
                found.append((row["uuid"], vec))
        return found

    def fts(self, match: str, scope: str | None, include_global: bool, limit: int = 30) -> dict[str, float]:
        where, params = _active_scope(scope, include_global, table="m")
        sql = f"""
            SELECT m.uuid AS uuid, bm25(memories_fts) AS rank
            FROM memories_fts
            JOIN memories m ON m.id = memories_fts.rowid
            WHERE memories_fts MATCH ? AND {where}
            ORDER BY rank
            LIMIT ?
        """
        try:
            with self._lock:
                rows = self.conn.execute(sql, [match, *params, clamp_limit(limit, 200)]).fetchall()
        except sqlite3.OperationalError:
            return {}
        scores: dict[str, float] = {}
        for row in rows:
            rank = float(row["rank"])
            scores[row["uuid"]] = -rank
        if not scores:
            return {}
        best = max(scores.values())
        worst = min(scores.values())
        if best == worst:
            # One hit, or every hit equally relevant. A zero span used to
            # collapse all scores to 0 and hide them from the result list.
            return {key: 1.0 for key in scores}
        span = best - worst
        return {key: (value - worst) / span for key, value in scores.items()}

    def get_many(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        by_id: dict[str, dict] = {}
        with self._lock:
            # Chunked so a large candidate list never exceeds SQLite's
            # parameter limit.
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"SELECT * FROM memories WHERE uuid IN ({marks})",
                    chunk,
                ).fetchall()
                by_id.update({row["uuid"]: row_to_dict(row) for row in rows})
        return [by_id[memory_id] for memory_id in ids if memory_id in by_id]

    def _migrate_columns(self) -> None:
        with self._lock:
            cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(memories)")}
            statements = []
            if "tier" not in cols:
                statements.append("ALTER TABLE memories ADD COLUMN tier TEXT NOT NULL DEFAULT 'durable'")
            if "recalls" not in cols:
                statements.append("ALTER TABLE memories ADD COLUMN recalls INTEGER NOT NULL DEFAULT 0")
            if "last_recalled_at" not in cols:
                statements.append("ALTER TABLE memories ADD COLUMN last_recalled_at TEXT")
            if "importance" not in cols:
                statements.append("ALTER TABLE memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 5")
            for sql in statements:
                self.conn.execute(sql)
            if statements:
                self.conn.commit()

    def _migrate_scopes(self) -> None:
        """Rewrite scopes that were stored in an older, unnormalized form.

        Older builds could keep a git URL with credentials in the scope column.
        Normalizing once removes those tokens from the database.
        """
        from memoryforge.scope import normalize_scope

        with self._lock:
            rows = self.conn.execute("SELECT DISTINCT scope FROM memories").fetchall()
            changed = 0
            for row in rows:
                old = row["scope"]
                new = normalize_scope(old) or "global"
                if new != old:
                    changed += self.conn.execute(
                        "UPDATE memories SET scope = ? WHERE scope = ?",
                        (new, old),
                    ).rowcount
            if changed:
                self.conn.commit()

    def backup_to(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        handle = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(handle)
        out = sqlite3.connect(dest)
        try:
            with self._lock:
                self.conn.backup(out)
        finally:
            out.close()
            try:
                os.chmod(dest, 0o600)
            except OSError:
                pass


def fts_query(text: str) -> str | None:
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    if not tokens:
        return None
    # Search the text column only. Without the column filter a query like
    # "github" or "fact" matches the scope and kind columns of every row.
    parts = ['text : "' + token.replace('"', "") + '"' for token in tokens[:12]]
    return " OR ".join(parts)


def _active_scope(scope: str | None, include_global: bool, table: str = "") -> tuple[str, list]:
    prefix = f"{table}." if table else ""
    where = f"{prefix}forgotten = 0 AND {prefix}superseded_by IS NULL"
    params: list = []
    if scope and scope not in {"", "all"}:
        if include_global and scope != "global":
            where += f" AND {prefix}scope IN (?, 'global')"
            params.append(scope)
        else:
            where += f" AND {prefix}scope = ?"
            params.append(scope)
    return where, params


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["uuid"],
        "scope": row["scope"],
        "text": row["text"],
        "kind": row["kind"],
        "source": row["source"],
        "confidence": row["confidence"],
        "pinned": bool(row["pinned"]),
        "forgotten": bool(row["forgotten"]),
        "superseded_by": row["superseded_by"],
        "tier": row["tier"] if "tier" in row.keys() else "durable",
        "recalls": int(row["recalls"]) if "recalls" in row.keys() and row["recalls"] is not None else 0,
        "last_recalled_at": row["last_recalled_at"] if "last_recalled_at" in row.keys() else None,
        "importance": int(row["importance"]) if "importance" in row.keys() and row["importance"] is not None else 5,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dream_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["uuid"],
        "scope": row["scope"],
        "phase": row["phase"],
        "summary": row["summary"],
        "created_at": row["created_at"],
    }


def _importance_for(kind: str) -> int:
    return {"preference": 7, "decision": 7, "convention": 6, "debug": 6}.get(kind, 5)
