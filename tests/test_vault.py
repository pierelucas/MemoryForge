import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from memoryforge.config import load_config
from memoryforge.db import Store
from memoryforge.paths import db_path
from memoryforge.server import create_app
from memoryforge.service import (
    MemoryService,
    age_days,
    promotable_daily,
    recency_weight,
)
from memoryforge.vault import read_projection, scope_dir


def test_recency_decay_spares_curated_rows():
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    old = (now - timedelta(days=30)).isoformat()
    assert recency_weight("daily", False, old, now) == 0.5
    assert recency_weight("durable", False, old, now) == 1.0
    assert recency_weight("daily", True, old, now) == 1.0
    assert age_days(old, now) == 30


def test_vault_splits_user_memory_and_daily_notes():
    service = MemoryService(load_config())
    service.add("Port ist 4737.", scope="global")
    service.store.set_kind(service.store.find_exact("global", "Port ist 4737.")["id"], "fact")
    preference = service.add("Bevorzuge pnpm.", scope="global")["memories"][0]
    service.store.set_kind(preference["id"], "preference")
    service.note("Heute den Port geprüft.", scope="global", source="test")
    service._sync("global")

    user = (scope_dir("global") / "USER.md").read_text(encoding="utf-8")
    memory = (scope_dir("global") / "MEMORY.md").read_text(encoding="utf-8")
    day = datetime.now(timezone.utc).date().isoformat()
    daily = (scope_dir("global") / "memory" / f"{day}.md").read_text(encoding="utf-8")
    assert "Bevorzuge pnpm." in user
    assert "Bevorzuge pnpm." not in memory
    assert "Port ist 4737." in memory
    assert "Heute den Port geprüft." in daily
    assert "sk-" not in memory


def test_secret_does_not_land_in_the_vault():
    service = MemoryService(load_config())
    service.add("Key api_key=sk-supersecretvalue123 bleibt draussen.", scope="global")
    text = (scope_dir("global") / "MEMORY.md").read_text(encoding="utf-8")
    assert "sk-supersecretvalue123" not in text
    assert "[redacted]" in text


def test_remove_scope_does_not_follow_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_DATA_DIR", str(tmp_path / "data"))
    from memoryforge.service import reset

    reset()
    from memoryforge.db import Store
    from memoryforge.paths import db_path
    from memoryforge.vault import remove_scope, scope_dir, write_scope

    store = Store(db_path())
    try:
        store.insert(text="Bleibt.", scope="project:github.com/acme/keep", kind="fact", source="test", embedding=None)
        write_scope(store, "project:github.com/acme/keep")
        keep = scope_dir("project:github.com/acme/keep")
        outside = tmp_path / "outside.txt"
        outside.write_text("SECRET-OUTSIDE", encoding="utf-8")
        (keep / "leak").symlink_to(outside)
        link = keep.parent / "link"
        link.symlink_to(keep, target_is_directory=True)

        remove_scope("project:github.com/acme/link")
        assert not link.exists() and not link.is_symlink()
        assert (keep / "MEMORY.md").is_file()
        assert outside.read_text(encoding="utf-8") == "SECRET-OUTSIDE"

        remove_scope("project:github.com/acme/keep")
        assert not keep.exists()
        assert outside.read_text(encoding="utf-8") == "SECRET-OUTSIDE"
    finally:
        store.close()


def test_scope_path_cannot_escape_the_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_DATA_DIR", str(tmp_path / "data"))
    escaped = scope_dir("project:../../etc")
    assert "etc" not in escaped.parts or escaped.is_relative_to(tmp_path / "data" / "vault")
    assert escaped.is_relative_to((tmp_path / "data" / "vault").resolve())
    assert ".." not in escaped.parts


def test_dream_promotes_an_old_decision_without_rewriting_it():
    cfg = load_config()
    cfg.llm.enabled = True

    class Quiet:
        def dream(self, scope, memories):
            return []

    service = MemoryService(cfg, llm=Quiet())
    created = service.note("Port bleibt 4737.", scope="global", source="test")["memories"][0]
    service.store.set_kind(created["id"], "decision")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat()
    service.store.conn.execute(
        "UPDATE memories SET created_at = ? WHERE uuid = ?",
        (yesterday, created["id"]),
    )
    service.store.conn.commit()
    assert promotable_daily(service.store.get(created["id"]))
    result = service.dream("global")
    assert result["ok"] is True
    assert result["promoted"] == 1
    row = service.store.get(created["id"])
    assert row["tier"] == "durable"
    assert row["text"] == "Port bleibt 4737."
    diary = (scope_dir("global") / "DREAMS.md").read_text(encoding="utf-8")
    assert "promoted verbatim" in diary
    assert "Port bleibt 4737." not in diary


def test_recalled_daily_fact_promotes_and_fresh_fact_does_not():
    cfg = load_config()
    cfg.llm.enabled = True

    class Quiet:
        def dream(self, scope, memories):
            return []

    service = MemoryService(cfg, llm=Quiet())
    fresh = service.note("Nur heute relevant.", scope="global")["memories"][0]
    hot = service.note("Der Hash-Embedder ist der Testmodus.", scope="global")["memories"][0]
    service.store.note_recalls([hot["id"]])
    service.store.note_recalls([hot["id"]])
    result = service.dream("global")
    assert service.store.get(fresh["id"])["tier"] == "daily"
    assert service.store.get(hot["id"])["tier"] == "durable"
    assert result["promoted"] == 1


def test_old_database_gains_tier_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_DATA_DIR", str(tmp_path))
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE memories (
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    store = Store(path)
    row = store.insert(text="Alt.", scope="global", kind="fact", source="test", embedding=None)
    assert row["tier"] == "durable"
    assert row["recalls"] == 0
    store.close()


def test_files_page_renders_projection_without_raw_html():
    service = MemoryService(load_config())
    service.add("Sichtbarer Fakt.", scope="global")
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/files?scope=global&file=memory")
        assert page.status_code == 200
        assert "Sichtbarer Fakt." in page.text
        assert "Editing a file does not change memory." in page.text
        name, text = read_projection("global", "memory")
        assert name == "MEMORY.md"
        assert "Sichtbarer Fakt." in text
