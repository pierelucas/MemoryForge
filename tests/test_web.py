from fastapi.testclient import TestClient

from memoryforge.config import load_config
from memoryforge.server import create_app
from memoryforge.service import get_service


def test_pages_roundtrip():
    app = create_app()
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "MemoryForge" in home.text
        assert "New memory" in home.text
        assert 'action="/backup"' not in home.text

        created = client.post("/memories", data={"text": "Die UI läuft lokal.", "scope": "global"}, follow_redirects=False)
        assert created.status_code == 303
        page = client.get("/")
        assert "Die UI läuft lokal." in page.text

        saved = client.post(
            "/settings",
            data={
                "enabled": "1",
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com",
                "model_choice": "deepseek-v4-pro",
                "model_custom": "",
                "thinking": "",
                "api_key": "test-key",
            },
            follow_redirects=True,
        )
        assert saved.status_code == 200
        assert "deepseek-v4-pro" in saved.text
        assert 'action="/backup"' in saved.text

        health = client.get("/api/health")
        assert health.json()["status"] == "ok"
        assert health.json()["memories"] >= 1


def test_project_view_includes_global_memories():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Globaler Fakt.", "scope": "global"})
        client.post("/memories", data={"text": "Nur hier.", "scope": "project:github.com/acme/demo"})
        page = client.get("/?scope=project:github.com/acme/demo")
        assert page.status_code == 200
        assert "Nur hier." in page.text
        assert "Globaler Fakt." in page.text
        assert "read here too" in page.text
        only_global = client.get("/?scope=global")
        assert "Nur hier." not in only_global.text
        assert "Globaler Fakt." in only_global.text


def test_language_switch_is_saved_and_defaults_to_english():
    app = create_app()
    with TestClient(app) as client:
        home = client.get("/")
        assert '<html lang="en">' in home.text
        assert "New memory" in home.text

        client.post("/settings", data={"lang": "de"}, follow_redirects=True)
        german = client.get("/")
        assert '<html lang="de">' in german.text
        assert "Neue Erinnerung" in german.text
        assert load_config().ui.lang == "de"

        client.post("/settings", data={"lang": "fr"}, follow_redirects=True)
        assert load_config().ui.lang == "en"
        assert "New memory" in client.get("/").text


def test_moving_a_memory_to_another_scope():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Gehört woanders hin.", "scope": "project:github.com/acme/old"})
        memory = get_service().list_memories("project:github.com/acme/old")[0]

        moved = client.post(
            f"/memories/{memory['id']}",
            data={"text": memory["text"], "scope": "project:github.com/acme/old", "memory_scope": "project:github.com/acme/new"},
            follow_redirects=False,
        )
        assert moved.status_code == 303
        assert "scope=project%3Agithub.com/acme/new" in moved.headers["location"]
        assert "Gehört woanders hin." in client.get("/?scope=project:github.com/acme/new").text
        assert "Gehört woanders hin." not in client.get("/?scope=project:github.com/acme/old").text
        assert get_service().store.get(memory["id"])["scope"] == "project:github.com/acme/new"


def test_moving_into_a_duplicate_is_rejected():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Doppelt.", "scope": "global"})
        client.post("/memories", data={"text": "Doppelt.", "scope": "project:github.com/acme/demo"})
        global_row = get_service().list_memories("global")[0]

        rejected = client.post(
            f"/memories/{global_row['id']}",
            data={"text": "Doppelt.", "scope": "global", "memory_scope": "project:github.com/acme/demo"},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "err=" in rejected.headers["location"]
        assert get_service().store.get(global_row["id"])["scope"] == "global"


def test_forgetting_a_whole_scope():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Projekt A.", "scope": "project:github.com/acme/a"})
        client.post("/memories", data={"text": "Projekt B.", "scope": "project:github.com/acme/b"})
        client.post("/memories", data={"text": "Global bleibt.", "scope": "global"})

        confirm = client.get("/scopes/forget?scope=project:github.com/acme/a")
        assert confirm.status_code == 200
        assert "Delete scope?" in confirm.text

        deleted = client.post("/scopes/forget", data={"scope": "project:github.com/acme/a"}, follow_redirects=False)
        assert deleted.status_code == 303
        assert "msg=" in deleted.headers["location"]
        assert "Projekt A." not in client.get("/").text
        assert "Projekt B." in client.get("/").text
        assert "Global bleibt." in client.get("/").text
        assert "project:github.com/acme/a" not in [row["scope"] for row in get_service().store.scopes()]

        missing = client.get("/scopes/forget?scope=project:github.com/acme/nope")
        assert missing.status_code == 404
        bad = client.post("/scopes/forget", data={"scope": "all"}, follow_redirects=False)
        assert "err=" in bad.headers["location"]


def test_global_scope_can_be_deleted_but_not_the_all_view():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Ein globaler Fakt.", "scope": "global"})
        assert client.get("/scopes/forget?scope=project:github.com/acme/x").status_code == 404
        assert client.get("/scopes/forget?scope=all").status_code == 404

        client.post("/scopes/forget", data={"scope": "global"}, follow_redirects=False)
        assert "Ein globaler Fakt." not in client.get("/").text
