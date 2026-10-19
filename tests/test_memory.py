import json

import pytest

from memoryforge.config import load_config, set_value
from memoryforge.llm import parse_actions
from memoryforge.safety import redact
from memoryforge.scope import normalize_remote, normalize_scope
from memoryforge.service import MemoryService


def test_add_search_forget_and_pin():
    service = MemoryService(load_config())
    created = service.add("Bevorzuge pnpm statt npm.", scope="global", source="test")
    assert created["llm"] is False
    memory_id = created["memories"][0]["id"]
    found = service.search("package manager pnpm", scope="global", include_global=False)
    assert any(row["id"] == memory_id for row in found)
    service.pin(memory_id, True)
    assert service.store.get(memory_id)["pinned"] is True
    service.forget(memory_id)
    again = service.search("pnpm", scope="global", include_global=False)
    assert all(row["id"] != memory_id for row in again)


def test_exact_duplicate_is_noop():
    service = MemoryService(load_config())
    service.add("Antworten auf Deutsch.", scope="global")
    second = service.add("Antworten auf Deutsch.", scope="global")
    assert second["noop"] is True
    assert service.store.count_active() == 1


def test_atomic_fact_does_not_call_llm_when_enabled():
    cfg = load_config()
    cfg.llm.enabled = True

    class Boom:
        def extract(self, *args, **kwargs):
            raise AssertionError("LLM should stay quiet for a single sentence")

    service = MemoryService(cfg, llm=Boom())
    result = service.add("Nutze uv statt pip.", scope="global")
    assert result["llm"] is False
    assert "uv" in result["memories"][0]["text"]


def test_long_text_uses_extractor():
    cfg = load_config()
    cfg.llm.enabled = True

    class Fake:
        def extract(self, text, scope, neighbors):
            return [{"op": "add", "text": "Das Repo nutzt FastAPI.", "kind": "convention"}]

    service = MemoryService(cfg, llm=Fake())
    blob = "Erster Satz über das Repo. Zweiter Satz über den Stack. Dritter Satz über Tests. Vierter Satz bleibt lang genug."
    result = service.add(blob, scope="project:github.com/acme/app")
    assert result["llm"] is True
    assert result["memories"][0]["text"] == "Das Repo nutzt FastAPI."
    assert result["memories"][0]["kind"] == "convention"


def test_supersede_hides_old_memory():
    service = MemoryService(load_config())
    old = service.add("Port ist 3000.", scope="global")["memories"][0]
    service.apply_actions(
        [{"op": "supersede", "replaces": [old["id"]], "text": "Port ist 4737.", "kind": "decision"}],
        scope="global",
        source="test",
    )
    texts = [row["text"] for row in service.list_memories("global")]
    assert "Port ist 4737." in texts
    assert "Port ist 3000." not in texts


def test_secret_is_redacted_before_store():
    service = MemoryService(load_config())
    result = service.add("Der Key ist api_key=sk-supersecretvalue123 und bleibt lokal.", scope="global")
    assert "sk-supersecretvalue123" not in result["memories"][0]["text"]
    assert "[redacted]" in result["memories"][0]["text"]


def test_parse_actions_accepts_fenced_json():
    raw = """```json
{"actions":[{"op":"add","text":"Nutze Tailscale.","kind":"decision"}]}
```"""
    actions = parse_actions(raw)
    assert actions[0]["text"] == "Nutze Tailscale."


def test_scope_normalizes_git_urls():
    assert normalize_remote("git@github.com:pierelucas/MemoryForge.git") == "github.com/pierelucas/MemoryForge"
    assert normalize_scope("https://github.com/pierelucas/MemoryForge.git") == "project:github.com/pierelucas/MemoryForge"


def test_config_set_model(tmp_path):
    cfg = load_config()
    set_value(cfg, "llm.model", "deepseek-v4-pro")
    set_value(cfg, "llm.enabled", "ja")
    again = load_config()
    assert again.llm.model == "deepseek-v4-pro"
    assert again.llm.enabled is True


def test_dream_without_llm_is_a_noop():
    service = MemoryService(load_config())
    service.add("Eins.", scope="global")
    service.add("Zwei.", scope="global")
    result = service.dream("global")
    assert result["ok"] is False
    assert service.store.count_active() == 2


def test_unknown_id():
    service = MemoryService(load_config())
    with pytest.raises(KeyError):
        service.forget("missing")
