import json

import httpx
import pytest
from fastapi.testclient import TestClient

from memoryforge.config import load_config, set_value
from memoryforge.llm import ChatLLM
from memoryforge.providers import (
    ProviderError,
    cached_models,
    fetch_models,
    models_endpoint,
    parse_model_list,
)
from memoryforge.server import create_app
from memoryforge.service import MemoryService


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload


def test_parse_model_list_keeps_chat_and_drops_embeddings():
    rows = parse_model_list(
        {
            "data": [
                {"id": "glm-5.3-flash", "name": "GLM-5.3-Flash", "type": "chat"},
                {"id": "text-embedding-3-small", "object": "model"},
                {"id": "whisper-1", "object": "model"},
                "llama3:latest",
            ]
        }
    )
    assert [row["id"] for row in rows] == ["glm-5.3-flash", "llama3:latest"]
    assert rows[0]["label"] == "GLM-5.3-Flash · glm-5.3-flash"


def test_opencode_go_catalog_is_not_the_chat_base():
    url = models_endpoint("opencode-go", "https://opencode.ai/inference/go/openai/v1")
    assert url == "https://opencode.ai/inference/go/v1/models"
    assert models_endpoint("custom", "http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1/models"


def test_fetch_models_uses_the_public_catalog_and_caches_it(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["follow"] = follow_redirects
        return _Response(
            200,
            {"data": [{"id": "glm-5.3-flash", "name": "GLM", "type": "chat"}, {"id": "text-embedding", "type": "embedding"}]},
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    rows = fetch_models("opencode-go", "https://opencode.ai/inference/go/openai/v1", "")
    assert [row["id"] for row in rows] == ["glm-5.3-flash"]
    assert seen["url"] == "https://opencode.ai/inference/go/v1/models"
    assert seen["headers"]["User-Agent"].startswith("MemoryForge/")
    assert seen["headers"]["x-opencode-session"] == "memoryforge"
    assert "Authorization" not in seen["headers"]
    assert seen["follow"] is True
    assert cached_models("opencode-go")[0]["id"] == "glm-5.3-flash"


def test_fetch_rejects_credentials_and_redacts_the_key(monkeypatch):
    with pytest.raises(ProviderError):
        fetch_models("custom", "http://user:pass@127.0.0.1/v1", "secret")

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        assert follow_redirects is False
        return _Response(401, {"error": "bad key secret"})

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ProviderError) as caught:
        fetch_models("openai", "https://api.openai.com/v1", "secret")
    assert "secret" not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_openai_call_does_not_send_thinking(monkeypatch):
    cfg = load_config()
    cfg.llm.provider = "openai"
    cfg.llm.base_url = "https://api.openai.com/v1"
    cfg.llm.model = "gpt-4.1-nano"
    cfg.llm.api_key = "sk-test"
    cfg.llm.thinking = False
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, follow_redirects=None):
        seen["body"] = json
        seen["headers"] = headers
        seen["follow"] = follow_redirects
        return _Response(200, {"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr("memoryforge.llm.httpx.post", fake_post)
    ChatLLM(cfg).ping()
    assert "thinking" not in seen["body"]
    assert seen["follow"] is False
    assert seen["headers"]["Authorization"] == "Bearer sk-test"


def test_deepseek_still_disables_thinking(monkeypatch):
    cfg = load_config()
    cfg.llm.api_key = "sk-test"
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, follow_redirects=None):
        seen["body"] = json
        return _Response(200, {"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr("memoryforge.llm.httpx.post", fake_post)
    ChatLLM(cfg).ping()
    assert seen["body"]["thinking"] == {"type": "disabled"}


def test_local_provider_allows_an_empty_key(monkeypatch):
    cfg = load_config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:11434/v1"
    cfg.llm.model = "llama3"
    cfg.llm.api_key = ""
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, follow_redirects=None):
        seen["headers"] = headers
        seen["url"] = url
        return _Response(200, {"choices": [{"message": {"content": "{\"actions\":[]}"}}]})

    monkeypatch.setattr("memoryforge.llm.httpx.post", fake_post)
    assert "actions" in ChatLLM(cfg).complete("system", "user")
    assert "Authorization" not in seen["headers"]
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"


def test_provider_switch_fills_the_default_url_unless_it_was_customized():
    cfg = load_config()
    set_value(cfg, "llm.provider", "openai")
    assert load_config().llm.base_url == "https://api.openai.com/v1"
    set_value(cfg, "llm.provider", "opencode-go")
    assert load_config().llm.base_url == "https://opencode.ai/inference/go/openai/v1"
    set_value(cfg, "llm.base_url", "https://proxy.example/v1")
    set_value(cfg, "llm.provider", "groq")
    assert load_config().llm.base_url == "https://proxy.example/v1"
    with pytest.raises(ValueError):
        set_value(cfg, "llm.provider", "no-such-provider")


def test_config_set_strips_and_masks_the_api_key():
    from typer.testing import CliRunner

    from memoryforge.cli import app

    result = CliRunner().invoke(app, ["config", "set", "llm.api_key", "  sk-secretvalue  "])
    assert result.exit_code == 0
    assert "sk-secretvalue" not in result.stdout
    assert "****alue" in result.stdout
    assert load_config().llm.api_key == "sk-secretvalue"


def test_settings_lists_opencode_go_and_loads_models(monkeypatch):
    monkeypatch.setattr(
        "memoryforge.server.resolve_models",
        lambda provider, base_url, api_key="": ([{"id": "glm-5.3-flash", "label": "GLM"}], "live", None),
    )
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/settings")
        assert "OpenCode Go" in page.text
        assert "opencode-go" in page.text
        loaded = client.post(
            "/api/models",
            data={"provider": "opencode-go", "base_url": "", "api_key": "go-key"},
        )
        assert loaded.status_code == 200
        assert loaded.json()["models"][0]["id"] == "glm-5.3-flash"
        assert "go-key" not in loaded.text


def test_export_and_import_roundtrip_redacts_secrets():
    service = MemoryService(load_config())
    service.add("Port ist 4737.", scope="global")
    payload = {"format": 1, "memories": service.export_rows(None)}
    payload["memories"].append(
        {
            "text": "Der Key ist api_key=sk-supersecretvalue123.",
            "scope": "project:github.com/acme/demo",
            "kind": "debug",
            "pinned": True,
        }
    )
    result = service.import_rows(payload)
    assert result["added"] == 1
    assert result["skipped"] == 1
    rows = service.store.all_active(None)
    blob = " ".join(row["text"] for row in rows)
    assert "sk-supersecretvalue123" not in blob
    imported = next(row for row in rows if row["scope"] == "project:github.com/acme/demo")
    assert imported["kind"] == "debug"
    assert imported["pinned"] is True
    assert "[redacted]" in imported["text"]
    again = service.import_rows(payload)
    assert again["added"] == 0
    assert again["skipped"] == 2


def test_memory_update_replaces_text_and_rejects_a_forgotten_row():
    service = MemoryService(load_config())
    row = service.add("Alter Fakt.", scope="global")["memories"][0]
    updated = service.update(row["id"], "Neuer Fakt.")
    assert updated["text"] == "Neuer Fakt."
    service.forget(row["id"])
    with pytest.raises(ValueError):
        service.update(row["id"], "Noch neuer.")
