from fastapi.testclient import TestClient

from memoryforge.config import load_config
from memoryforge.paths import data_dir
from memoryforge.server import create_app
from memoryforge.service import get_service


def _stored_bytes() -> bytes:
    root = data_dir()
    blobs = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                blobs.append(path.read_bytes())
    return b"".join(blobs)


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


def test_editing_into_a_duplicate_in_the_same_scope_is_rejected():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Eins.", "scope": "global"})
        client.post("/memories", data={"text": "Zwei.", "scope": "global"})
        first = next(row for row in get_service().list_memories("global") if row["text"] == "Eins.")

        rejected = client.post(
            f"/memories/{first['id']}",
            data={"text": "Zwei.", "scope": "global", "memory_scope": "global"},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "err=" in rejected.headers["location"]
        assert get_service().store.get(first["id"])["text"] == "Eins."


def test_empty_project_page_has_one_hint_and_no_delete_link():
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/?scope=project:github.com/acme/empty")
        assert page.text.count("Nothing in this project yet.") == 1
        assert "/scopes/forget" not in page.text


def test_deleting_a_scope_erases_related_data_from_disk():
    token = "PURGE-TOKEN-9f3c1a7e-scope-secret"
    other = "Andere Scope bleibt stehen."
    scope = "project:github.com/acme/purge"
    kept = "project:github.com/acme/keep"
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": f"Aktiv {token}.", "scope": scope})
        client.post("/memories", data={"text": f"Vergessen {token}.", "scope": scope})
        client.post("/memories", data={"text": f"Ersetzt {token}.", "scope": scope})
        client.post("/memories", data={"text": other, "scope": kept})
        service = get_service()
        forgotten = service.store.find_exact(scope, f"Vergessen {token}.")
        service.forget(forgotten["id"])
        old = service.store.find_exact(scope, f"Ersetzt {token}.")
        current = service.store.find_exact(scope, f"Aktiv {token}.")
        service.store.supersede([old["id"]], current["id"], scope=scope)
        service.store.insert_dream(scope, "sweep", f"Traum {token}.")
        service.set_persona(scope, "soul", f"Stimme {token}.")
        service._sync(scope, kept)

        from memoryforge.vault import scope_dir

        assert token.encode() in (scope_dir(scope) / "SOUL.md").read_bytes()
        confirm = client.get(f"/scopes/forget?scope={scope}")
        assert confirm.status_code == 200
        assert "3 memories" in confirm.text
        assert "1 dreams" in confirm.text
        assert "1 persona" in confirm.text

        deleted = client.post("/scopes/forget", data={"scope": scope}, follow_redirects=False)
        assert deleted.status_code == 303
        assert service.store.scope_counts(scope) == {"memories": 0, "dreams": 0, "personas": 0}
        assert service.store.get(forgotten["id"]) is None
        assert service.store.find_exact(kept, other)
        assert not scope_dir(scope).exists()
        kept_memory = (scope_dir(kept) / "MEMORY.md").read_text(encoding="utf-8")
        assert other in kept_memory
        assert token not in kept_memory
        assert token.encode() not in _stored_bytes()
        assert all(token not in row["text"] for row in service.search(token, limit=10))
        gone = client.post("/scopes/forget", data={"scope": scope}, follow_redirects=False)
        assert gone.status_code == 404


def test_hidden_scope_can_still_be_deleted_from_disk():
    scope = "project:github.com/acme/old"
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Nur noch vergessen.", "scope": scope})
        row = get_service().store.find_exact(scope, "Nur noch vergessen.")
        get_service().forget(row["id"])

        home = client.get("/")
        assert scope in home.text
        assert "/scopes/forget?scope=project%3Agithub.com/acme/old" in home.text

        confirm = client.get(f"/scopes/forget?scope={scope}")
        assert confirm.status_code == 200
        deleted = client.post("/scopes/forget", data={"scope": scope}, follow_redirects=False)
        assert deleted.status_code == 303
        assert get_service().store.scope_counts(scope)["memories"] == 0
        assert scope not in client.get("/").text


def test_forgetting_a_whole_scope():
    app = create_app()
    with TestClient(app) as client:
        client.post("/memories", data={"text": "Projekt A.", "scope": "project:github.com/acme/a"})
        client.post("/memories", data={"text": "Projekt B.", "scope": "project:github.com/acme/b"})
        client.post("/memories", data={"text": "Global bleibt.", "scope": "global"})

        page = client.get("/?scope=project:github.com/acme/a")
        assert page.status_code == 200
        assert page.text.count('class="danger"') >= 2
        assert "Delete scope" in page.text
        assert "/scopes/forget?scope=project%3Agithub.com/acme/a" in page.text

        confirm = client.get("/scopes/forget?scope=project:github.com/acme/a")
        assert confirm.status_code == 200
        assert "Delete scope?" in confirm.text
        assert "cannot be undone" in confirm.text
        assert "stay in the database" not in confirm.text

        deleted = client.post("/scopes/forget", data={"scope": "project:github.com/acme/a"}, follow_redirects=False)
        assert deleted.status_code == 303
        assert "msg=" in deleted.headers["location"]
        assert "Projekt A." not in client.get("/").text
        assert "Projekt B." in client.get("/").text
        assert "Global bleibt." in client.get("/").text
        assert get_service().store.scope_counts("project:github.com/acme/a") == {
            "memories": 0,
            "dreams": 0,
            "personas": 0,
        }
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
        assert get_service().store.scope_counts("global")["memories"] == 0
