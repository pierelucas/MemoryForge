from fastapi.testclient import TestClient

from memoryforge.config import load_config
from memoryforge.persona import context_card, parse_identity
from memoryforge.server import create_app
from memoryforge.service import MemoryService
from memoryforge.vault import scope_dir


def test_persona_is_in_the_session_card_and_vault():
    service = MemoryService(load_config())
    service.set_persona("global", "identity", "name: Forge\nvibe: precise\nemoji: *")
    service.set_persona("global", "soul", "No filler. No invented facts.")
    service.set_persona("project:github.com/acme/app", "soul", "Follow the repo conventions.")
    card = service.brief("project:github.com/acme/app")
    assert "Forge" in card["card"]
    assert "No filler." in card["card"]
    assert "Follow the repo conventions." in card["card"]
    assert "Project voice wins" in card["card"]
    soul = (scope_dir("global") / "SOUL.md").read_text(encoding="utf-8")
    assert "No filler." in soul
    project = (scope_dir("project:github.com/acme/app") / "SOUL.md").read_text(encoding="utf-8")
    assert "Follow the repo conventions." in project


def test_empty_persona_clears_and_dream_does_not_touch_it():
    service = MemoryService(load_config())
    service.set_persona("global", "soul", "Stay sharp.")
    assert service.set_persona("global", "soul", "   ") is None
    assert service.persona_view("global")["global"]["soul"] == ""
    service.set_persona("global", "soul", "Stay sharp.")
    service.add("Eins.", scope="global")
    service.add("Zwei.", scope="global")
    result = service.dream("global")
    assert result["ok"] is False
    assert service.persona_view("global")["global"]["soul"] == "Stay sharp."


def test_persona_rejects_secrets_and_overlong_voice():
    service = MemoryService(load_config())
    service.set_persona("global", "soul", "Key api_key=sk-supersecretvalue123")
    assert "sk-supersecretvalue123" not in service.persona_view("global")["global"]["soul"]
    try:
        service.set_persona("global", "soul", "x" * 2001)
    except ValueError as exc:
        assert exc.key == "error.persona_limit"
    else:
        raise AssertionError("overlong soul was accepted")


def test_identity_parse_and_card_are_short():
    fields = parse_identity("name: Forge\nvibe: calm\nextra line")
    assert fields["name"] == "Forge"
    assert "extra line" in fields["extra"]
    card = context_card(
        scope="global",
        persona={"global": {"identity": "name: Forge", "soul": ""}, "project": None},
        directives=[],
        standing=[],
        durable=[],
        daily=[],
    )
    assert "Forge" in card
    assert "unset" in card


def test_persona_page_saves_and_previews_the_card():
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/persona?scope=global")
        assert page.status_code == 200
        assert "Session card" in page.text
        saved = client.post(
            "/persona",
            data={"scope": "global", "name": "Forge", "vibe": "precise", "emoji": "*", "soul": "No filler."},
            follow_redirects=False,
        )
        assert saved.status_code == 303
        again = client.get("/persona?scope=global")
        assert "Forge" in again.text
        assert "No filler." in again.text
