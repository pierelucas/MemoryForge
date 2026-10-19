from fastapi.testclient import TestClient

from memoryforge.server import create_app


def test_pages_roundtrip():
    app = create_app()
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "MemoryForge" in home.text
        assert "Neue Erinnerung" in home.text

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
        assert "wird hier mitgelesen" in page.text
        only_global = client.get("/?scope=global")
        assert "Nur hier." not in only_global.text
        assert "Globaler Fakt." in only_global.text
