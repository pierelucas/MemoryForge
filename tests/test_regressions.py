import asyncio
import sys
import types
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryforge.backup import create_backup, restore_backup
from memoryforge.config import ConfigError, load_config
from memoryforge.db import clamp_limit
from memoryforge.embed import FastEmbedder
from memoryforge.llm import LLMError, parse_actions
from memoryforge.mcp_server import build_mcp
from memoryforge.paths import db_path
from memoryforge.scope import normalize_scope
from memoryforge.server import create_app
from memoryforge.service import MemoryService, reset


def _service(cfg=None, llm=None) -> MemoryService:
    return MemoryService(cfg or load_config(), llm=llm)


def test_fts_matches_text_not_scope_or_kind():
    service = _service()
    created = service.add("Der Port ist 4737.", scope="project:github.com/acme/demo")
    assert created["memories"]
    # "github" and "fact" only exist in the scope and kind columns.
    scope = "project:github.com/acme/demo"
    assert service.store.fts('text : "github"', scope, False) == {}
    assert service.store.fts('text : "fact"', scope, False) == {}
    assert service.store.fts('text : "4737"', scope, False)


def test_single_fts_hit_scores_one():
    service = _service()
    service.add("Der Port ist 4737.", scope="global")
    scores = service.store.fts('text : "4737"', "global", False)
    assert scores
    assert max(scores.values()) == 1.0


def test_llm_noop_does_not_store_a_fallback_copy():
    cfg = load_config()
    seed = _service(cfg)
    existing = seed.add("Antworten dürfen Deutsch sein.", scope="global")["memories"][0]
    cfg.llm.enabled = True

    class NoopLLM:
        def extract(self, text, scope, neighbors):
            return [{"op": "noop", "replaces": [existing["id"]]}]

    service = _service(cfg, llm=NoopLLM())
    blob = "Erster Satz. Zweiter Satz. Dritter Satz. Vierter Satz ist lang genug."
    result = service.add(blob, scope="global")
    assert result["noop"] is True
    assert [row["id"] for row in result["memories"]] == [existing["id"]]
    assert service.store.count_active() == 1


def test_fastembed_failure_falls_back_to_hash(monkeypatch, capsys):
    fake = types.ModuleType("fastembed")

    class Unavailable:
        def __init__(self, **kwargs):
            raise RuntimeError("model download failed")

    fake.TextEmbedding = Unavailable
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    embedder = FastEmbedder("missing/model")
    vector = embedder.embed_many(["Hallo Welt"])[0]
    assert len(vector) == 64
    assert embedder.name == "hash"
    assert "Hash-Fallback" in capsys.readouterr().err


def test_invalid_llm_json_raises_llm_error():
    with pytest.raises(LLMError):
        parse_actions("das ist kein json")


def test_api_failure_stores_the_raw_text():
    cfg = load_config()
    cfg.llm.enabled = True

    class BrokenLLM:
        def extract(self, text, scope, neighbors):
            raise LLMError("API 500")

    service = _service(cfg, llm=BrokenLLM())
    blob = "Erster Satz. Zweiter Satz. Dritter Satz. Vierter Satz ist lang genug."
    result = service.add(blob, scope="global")
    assert result["memories"][0]["text"] == blob
    assert result["warning"]


def test_supersede_cannot_touch_another_scope():
    service = _service()
    old = service.add("Port ist 3000.", scope="global")["memories"][0]
    service.apply_actions(
        [{"op": "supersede", "replaces": [old["id"]], "text": "Port ist 4737.", "kind": "decision"}],
        scope="project:github.com/acme/demo",
        source="test",
    )
    assert service.store.get(old["id"])["superseded_by"] is None
    assert "Port ist 3000." in [row["text"] for row in service.list_memories("global")]


def test_scope_strips_credentials_and_variants():
    expected = "project:github.com/acme/demo"
    assert normalize_scope("https://user:secret@github.com/acme/demo.git") == expected
    assert normalize_scope("ssh://git@github.com/acme/demo.git") == expected
    assert normalize_scope("git@github.com:acme/demo.git") == expected
    assert normalize_scope("project:github.com/acme/demo/") == expected
    assert normalize_scope("project:https://github.com/acme/demo.git/") == expected
    assert normalize_scope("project:") == ""


def test_duplicate_check_folds_unicode_case():
    service = _service()
    service.add("Über alles.", scope="global")
    second = service.add("über alles.", scope="global")
    assert second["noop"] is True
    assert service.store.count_active() == 1


def test_limit_is_clamped():
    assert clamp_limit(-1) == 1
    assert clamp_limit(0) == 1
    assert clamp_limit(10_000) == 200


def test_invalid_port_is_a_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "config.toml"
    path.write_text('[server]\nport = "abc"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_ui_redirects_to_the_normalized_scope():
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/memories",
            data={
                "text": "Die UI normalisiert den Scope.",
                "scope": "",
                "scope_custom": "https://github.com/acme/demo.git",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        location = created.headers["location"]
        assert "project%3Agithub.com/acme/demo" in location
        page = client.get(location)
        assert "Die UI normalisiert den Scope." in page.text


def test_cross_site_post_is_rejected():
    app = create_app()
    with TestClient(app) as client:
        blocked = client.post(
            "/memories",
            data={"text": "Von außen.", "scope": "global"},
            headers={"Origin": "https://evil.example"},
        )
        assert blocked.status_code == 403
        allowed = client.post(
            "/memories",
            data={"text": "Von hier.", "scope": "global"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        assert allowed.status_code == 303


def test_restore_removes_stale_wal_and_keeps_permissions(tmp_path):
    cfg = load_config()
    service = _service(cfg)
    service.add("WAL-Test.", scope="global")
    archive = tmp_path / "move.zip"
    create_backup(archive, include_secrets=False)
    reset()
    info = restore_backup(archive)
    assert info["warning"] == ""
    assert not Path(str(db_path()) + "-wal").exists()
    assert not Path(str(db_path()) + "-shm").exists()
    assert (db_path().stat().st_mode & 0o777) == 0o600
    with zipfile.ZipFile(archive) as handle:
        assert "memory.db" in handle.namelist()


def test_dream_reviews_more_than_eighty_rows():
    cfg = load_config()
    service = _service(cfg)
    for index in range(90):
        service.add(f"Fakt Nummer {index}.", scope="global")

    class QuietLLM:
        def dream(self, scope, memories):
            return []

    cfg.llm.enabled = True
    service.llm = QuietLLM()
    result = service.dream("global")
    assert result["ok"] is True
    assert result["reviewed"] == 90


def test_mcp_reports_unknown_ids_instead_of_raising():
    mcp = build_mcp()

    async def call():
        return await mcp.call_tool("memory_forget", {"memory_id": "missing"})

    result = asyncio.run(call())
    content = result[1] if isinstance(result, tuple) else result
    text = content[0].text if isinstance(content, list) else str(content)
    assert "Unbekannte Id" in text
