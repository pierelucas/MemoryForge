from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mcp.server.transport_security import TransportSecuritySettings
from starlette.background import BackgroundTask
from starlette.types import ASGIApp, Receive, Scope, Send

from memoryforge import __version__
from memoryforge.config import PROVIDERS, known_model, load_config, model_catalog
from memoryforge.providers import ProviderError, provider_or_custom, resolve_models
from memoryforge.i18n import kind_label, normalize_lang, translate
from memoryforge.scope import normalize_scope, scope_label, scope_path_label
from memoryforge.service import get_service, seed_demo

PACKAGE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE / "templates"))


class _McpSlash:
    """Clients call /mcp and /mcp/. Starlette's mount only serves the slashed form."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class _BrowserGuard:
    """Reject cross-site writes and DNS-rebinding requests against the notebook.

    curl, the MCP client, and other tools send no Origin header and keep
    working. A browser always sends one for a cross-site form POST, which is
    the case this blocks.
    """

    def __init__(self, app: ASGIApp, bind_host: str) -> None:
        self.app = app
        self.local_only = bind_host in {"127.0.0.1", "localhost", "::1"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        origin = headers.get("origin") or headers.get("referer")
        host = headers.get("host", "")
        # Always check the Host header on a loopback bind. A DNS-rebinding
        # request arrives with the attacker's hostname even without Origin.
        if self.local_only and not _host_allowed(host):
            await _plain(send, 421, "Invalid Host header")
            return
        if origin and not _origin_matches(origin, host, scope.get("scheme", "http")):
            await _plain(send, 403, "Cross-site request rejected")
            return
        await self.app(scope, receive, send)


def _host_name(host: str) -> str:
    try:
        return (urlsplit("//" + host).hostname or "").lower()
    except ValueError:
        return ""


def _host_port(host: str, default: int) -> int:
    try:
        return urlsplit("//" + host).port or default
    except ValueError:
        return default


def _host_allowed(host: str) -> bool:
    return _host_name(host) in _LOCAL_HOSTS


def _origin_matches(origin: str, host: str, scheme: str = "http") -> bool:
    if origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    default = 443 if parsed.scheme == "https" else 80
    try:
        origin_port = parsed.port or default
    except ValueError:
        return False
    host_default = 443 if scheme == "https" else 80
    return (parsed.hostname or "").lower() == _host_name(host) and origin_port == _host_port(host, host_default)


async def _plain(send: Send, status: int, body: str) -> None:
    payload = body.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


def create_app() -> FastAPI:
    from memoryforge.mcp_server import build_mcp

    bind = os.environ.get("MEMORYFORGE_BIND_HOST", "127.0.0.1")
    mcp = build_mcp()
    security = None
    if bind in {"127.0.0.1", "localhost", "::1"}:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
    mcp_http = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        host=bind,
        transport_security=security,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if os.environ.get("MEMORYFORGE_DEMO") == "1":
            seed_demo()
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MemoryForge", version=__version__, lifespan=lifespan)
    app.add_middleware(_McpSlash)
    app.add_middleware(_BrowserGuard, bind_host=bind)
    app.mount("/static", StaticFiles(directory=str(PACKAGE / "static")), name="static")
    app.mount("/mcp", mcp_http)

    @app.get("/api/health")
    def health():
        service = get_service()
        return {
            "status": "ok",
            "version": __version__,
            "memories": service.store.count_active(),
            "embedder": service.embedder.name,
            "llm": service.cfg.llm.enabled,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, q: str = "", scope: str = "", layer: str = "", msg: str = "", err: str = ""):
        service = get_service()
        # Normalize here as well: a git URL or trailing slash in the address
        # bar used to select nothing in the sidebar and fall back to global
        # in the composer.
        active = normalize_scope(scope)
        chosen = layer if layer in {"durable", "daily", "dreams"} else ""
        tier = chosen if chosen in {"durable", "daily"} else None
        also: list = []
        dreams: list = []
        if chosen == "dreams":
            rows = []
            dreams = service.list_dreams(active or None, limit=40)
        elif q.strip():
            rows = service.search(
                q.strip(),
                scope=active or None,
                limit=40,
                include_global=bool(active) and active != "global",
                record=True,
            )
            if tier:
                rows = [row for row in rows if (row.get("tier") or "durable") == tier]
        elif active and active != "global":
            rows = service.list_memories(active, limit=80, tier=tier)
            also = service.list_memories("global", limit=40, tier=tier)
        else:
            rows = service.list_memories(active or None, limit=80, tier=tier)
        persona_line = ""
        if active:
            from memoryforge.persona import identity_line

            view = service.persona_view(active)
            own = view["global"] if active == "global" else (view.get("project") or {})
            persona_line = identity_line((own or {}).get("identity") or "")
            if not persona_line:
                soul = ((own or {}).get("soul") or "").strip()
                persona_line = soul.splitlines()[0][:80] if soul else ""
        counts = service.store.tier_counts(active or None)
        if active and active != "global":
            extra = service.store.tier_counts("global")
            counts = {
                "durable": counts.get("durable", 0) + extra.get("durable", 0),
                "daily": counts.get("daily", 0) + extra.get("daily", 0),
            }
        return templates.TemplateResponse(
            request,
            "index.html",
            _page(
                request,
                rows=rows,
                also=also,
                dreams=dreams,
                q=q,
                active=active,
                layer=chosen,
                counts=counts,
                dream_count=len(service.list_dreams(active or None, limit=200)),
                persona_line=persona_line,
                msg=msg,
                err=err,
            ),
        )

    @app.post("/memories")
    def create_memory(
        text: str = Form(...),
        scope: str = Form(""),
        scope_custom: str = Form(""),
        tier: str = Form("durable"),
    ):
        service = get_service()
        lang = load_config().ui.lang
        chosen = normalize_scope(scope_custom or scope or "global") or "global"
        daily = tier == "daily"
        try:
            if daily:
                result = service.note(text, scope=chosen, source="ui", detect=False)
            else:
                result = service.add(text, scope=chosen, source="ui", detect=False)
        except ValueError as exc:
            return _redirect("/", err=_error(lang, exc))
        stored_scope = result["memories"][0]["scope"] if result["memories"] else chosen
        if result["noop"]:
            key = "flash.already_saved" if result["memories"] else "flash.nothing_new"
            return _redirect(_home(stored_scope, translate(lang, key), layer="daily" if daily else ""))
        return _redirect(_home(stored_scope, translate(lang, "flash.saved"), layer="daily" if daily else ""))

    @app.post("/memories/{memory_id}")
    def edit_memory(
        memory_id: str,
        text: str = Form(...),
        scope: str = Form(""),
        memory_scope: str = Form(""),
        scope_custom: str = Form(""),
    ):
        service = get_service()
        lang = load_config().ui.lang
        current = service.store.get(memory_id)
        if current is None:
            raise HTTPException(status_code=404)
        target = scope_custom.strip() or memory_scope
        try:
            row = service.update(memory_id, text, scope=target or None)
        except KeyError:
            raise HTTPException(status_code=404) from None
        except ValueError as exc:
            return _redirect(_home(normalize_scope(scope), ""), err=_error(lang, exc))
        view = normalize_scope(scope)
        # A move out of the scope you are looking at follows the row, so the
        # page does not fall back to an empty list.
        destination = row["scope"] if view and view == current["scope"] != row["scope"] else (view or row["scope"])
        return _redirect(_home(destination, translate(lang, "flash.updated")))

    @app.get("/memories/{memory_id}/forget", response_class=HTMLResponse)
    def forget_confirm(request: Request, memory_id: str):
        row = get_service().store.get(memory_id)
        if row is None or row["forgotten"]:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request,
            "forget.html",
            _page(request, memory=_view(row, load_config().ui.lang), active=row["scope"]),
        )

    @app.post("/memories/{memory_id}/forget")
    def forget_memory(memory_id: str):
        service = get_service()
        row = service.store.get(memory_id)
        if row is None or row["forgotten"]:
            raise HTTPException(status_code=404)
        service.forget(memory_id)
        return _redirect(_home(row["scope"], translate(load_config().ui.lang, "flash.forgotten")))

    @app.get("/scopes/forget", response_class=HTMLResponse)
    def forget_scope_confirm(request: Request, scope: str = ""):
        resolved = normalize_scope(scope)
        if not resolved or resolved == "global":
            raise HTTPException(status_code=404)
        service = get_service()
        foot = service.scope_footprint(resolved)
        if not (foot["memories"] or foot["dreams"] or foot["personas"] or foot["vault"]):
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request,
            "forget_scope.html",
            _page(
                request,
                active=resolved,
                target_scope=resolved,
                count=foot["memories"],
                dreams=foot["dreams"],
                personas=foot["personas"],
            ),
        )

    @app.post("/scopes/forget")
    def forget_scope(scope: str = Form("")):
        lang = load_config().ui.lang
        try:
            count = get_service().forget_scope(scope)
        except KeyError:
            raise HTTPException(status_code=404) from None
        except ValueError as exc:
            return _redirect("/", err=_error(lang, exc))
        return _redirect("/", msg=translate(lang, "flash.scope_forgotten", count=count))

    @app.get("/scopes/reset", response_class=HTMLResponse)
    def reset_scope_confirm(request: Request):
        service = get_service()
        foot = service.scope_footprint("global")
        if not (foot["memories"] or foot["dreams"] or foot["personas"] or foot["vault"]):
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request,
            "reset_scope.html",
            _page(
                request,
                active="global",
                count=foot["memories"],
                dreams=foot["dreams"],
                personas=foot["personas"],
            ),
        )

    @app.post("/scopes/reset")
    def reset_scope():
        lang = load_config().ui.lang
        try:
            count = get_service().reset_scope("global")
        except KeyError:
            raise HTTPException(status_code=404) from None
        except ValueError as exc:
            return _redirect("/?scope=global", err=_error(lang, exc))
        return _redirect(_home("global", translate(lang, "flash.scope_reset", count=count)))

    @app.post("/memories/{memory_id}/pin")
    def pin_memory(memory_id: str, scope: str = Form("")):
        row = get_service().store.get(memory_id)
        if row is None:
            raise HTTPException(status_code=404)
        get_service().pin(memory_id, not row["pinned"])
        return _redirect(_home(scope or row["scope"]))

    @app.get("/persona", response_class=HTMLResponse)
    def persona_page(request: Request, scope: str = "", msg: str = "", err: str = ""):
        from memoryforge.persona import parse_identity

        service = get_service()
        active = normalize_scope(scope) or "global"
        view = service.persona_view(active)
        own = view["global"] if active == "global" else (view["project"] or {"identity": "", "soul": ""})
        card = service.brief(active).get("card") or ""
        return templates.TemplateResponse(
            request,
            "persona.html",
            _page(
                request,
                active=active,
                section="persona",
                identity=parse_identity(own.get("identity") or ""),
                soul=own.get("soul") or "",
                card=card,
                msg=msg,
                err=err,
            ),
        )

    @app.post("/persona")
    def save_persona(
        scope: str = Form("global"),
        name: str = Form(""),
        vibe: str = Form(""),
        emoji: str = Form(""),
        soul: str = Form(""),
    ):
        from memoryforge.persona import format_identity

        lang = load_config().ui.lang
        resolved = normalize_scope(scope) or "global"
        service = get_service()
        try:
            service.set_persona(resolved, "identity", format_identity(name, vibe, emoji))
            service.set_persona(resolved, "soul", soul)
        except ValueError as exc:
            return _redirect(f"/persona?scope={quote(resolved)}", err=_error(lang, exc))
        return _redirect(f"/persona?scope={quote(resolved)}", msg=translate(lang, "flash.saved"))

    @app.get("/files", response_class=HTMLResponse)
    def files(request: Request, scope: str = "", file: str = "memory"):
        from memoryforge.vault import list_projection, read_projection, render_preview, write_scopes

        service = get_service()
        active = normalize_scope(scope) or "global"
        try:
            write_scopes(service.store, [active])
            name, text = read_projection(active, file or "memory")
            listing = list_projection(active)
        except (OSError, ValueError):
            name, text, listing = "MEMORY.md", "", []
        return templates.TemplateResponse(
            request,
            "files.html",
            _page(
                request,
                active=active,
                file_key=file or "memory",
                file_name=name,
                file_html=render_preview(text),
                file_empty=not text.strip(),
                projection=listing,
                section="files",
            ),
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, msg: str = "", err: str = ""):
        cfg = load_config()
        return templates.TemplateResponse(
            request,
            "settings.html",
            _page(
                request,
                cfg=cfg,
                providers=PROVIDERS,
                catalog=model_catalog(),
                known=known_model(cfg.llm.model, cfg.llm.provider),
                msg=msg,
                err=err,
                active="settings",
            ),
        )

    @app.post("/settings")
    def save_settings(
        enabled: str = Form(""),
        provider: str = Form("deepseek"),
        base_url: str = Form(""),
        model_choice: str = Form(""),
        model_custom: str = Form(""),
        thinking: str = Form(""),
        api_key: str = Form(""),
        clear_key: str = Form(""),
        lang: str = Form("en"),
    ):
        cfg = load_config()
        cfg.ui.lang = normalize_lang(lang)
        cfg.llm.enabled = enabled == "1"
        provider = provider_or_custom(provider)
        old_default = (PROVIDERS.get(cfg.llm.provider) or {}).get("base_url") or ""
        new_default = (PROVIDERS.get(provider) or {}).get("base_url") or ""
        cfg.llm.provider = provider
        custom = model_custom.strip()
        chosen = custom or model_choice.strip() or cfg.llm.model
        if chosen == "__custom__":
            chosen = custom or cfg.llm.model
        cfg.llm.model = chosen
        url = base_url.strip()
        # The form can still hold the previous provider's default when the
        # browser has no script. A URL the user typed is left alone.
        if not url or url == old_default:
            url = new_default or url
        cfg.llm.base_url = url
        cfg.llm.thinking = thinking == "1"
        if clear_key == "1":
            cfg.llm.api_key = ""
        elif api_key.strip():
            cfg.llm.api_key = api_key.strip()
        cfg.save()
        return _redirect("/settings?msg=" + quote(translate(cfg.ui.lang, "flash.saved")))

    @app.post("/settings/test")
    def test_settings():
        service = get_service()
        lang = load_config().ui.lang
        if not service.cfg.llm.enabled:
            return _redirect("/settings?err=" + quote(translate(lang, "flash.ai_off")))
        try:
            result = service.llm.ping()
        except Exception as exc:  # noqa: BLE001 — show the provider error on the settings page
            message = str(exc)
            return _redirect("/settings?err=" + quote(message[:240]))
        model = result.get("model") or service.cfg.llm.model
        return _redirect("/settings?msg=" + quote(translate(lang, "flash.reachable", model=model)))

    @app.post("/dream")
    def dream(scope: str = Form("")):
        lang = load_config().ui.lang
        result = get_service().dream(scope or None)
        target = "/settings" if not scope else _home(scope)
        key = "msg" if result.get("ok") else "err"
        join = "&" if "?" in target else "?"
        message = translate(lang, result["key"], **result.get("params", {})) if result.get("key") else result.get("message")
        return _redirect(f"{target}{join}{key}=" + quote(message or translate(lang, "flash.done")))

    @app.post("/api/models")
    def api_models(
        provider: str = Form("deepseek"),
        base_url: str = Form(""),
        api_key: str = Form(""),
    ):
        cfg = load_config()
        key_name = provider_or_custom(provider)
        typed = api_key.strip()
        # A key stored for another provider must not be sent to this one.
        stored = cfg.llm.api_key if key_name == cfg.llm.provider else ""
        url = base_url.strip() or (cfg.llm.base_url if key_name == cfg.llm.provider else "")
        try:
            models, source, error = resolve_models(key_name, url, typed or stored)
        except ProviderError as exc:
            return JSONResponse({"models": [], "error": str(exc)[:240]}, status_code=400)
        return {"models": models, "source": source, "error": error}

    @app.post("/export")
    def export_now():
        import json

        payload = {"format": 1, "memories": get_service().export_rows(None)}
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="memoryforge-memories.json"'},
        )

    @app.post("/backup")
    def backup_now(secrets: str = Form("1")):
        import tempfile

        from memoryforge.backup import create_backup

        handle, name = tempfile.mkstemp(prefix="memoryforge-backup-", suffix=".zip")
        os.close(handle)
        dest = Path(name)
        try:
            create_backup(dest, include_secrets=secrets == "1")
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        # The archive may contain the API key. Remove it once it is sent.
        return FileResponse(
            dest,
            filename="memoryforge-backup.zip",
            media_type="application/zip",
            background=BackgroundTask(dest.unlink, missing_ok=True),
        )

    @app.get("/api/memories")
    def api_list(q: str = "", scope: str = "", limit: int = 20):
        service = get_service()
        if q.strip():
            rows = service.search(q.strip(), scope=scope or None, limit=limit)
        else:
            rows = service.list_memories(scope or None, limit=limit)
        return {"memories": rows}

    @app.post("/api/memories")
    def api_add(payload: dict):
        text = str(payload.get("text") or "")
        scope = payload.get("scope")
        try:
            result = get_service().add(text, scope=scope, source="api", detect=False)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return result

    return app


def _page(request: Request, **extra) -> dict:
    service = get_service()
    lang = load_config().ui.lang
    scopes = service.store.scopes()
    context = {
        "request": request,
        "version": __version__,
        "lang": lang,
        "t": lambda key, **params: translate(lang, key, **params),
        "scopes": [
            {
                "scope": row["scope"],
                "count": row["count"],
                "label": scope_label(row["scope"]),
                "path_label": scope_path_label(row["scope"]),
            }
            for row in scopes
        ],
        "total": service.store.count_active(),
        "can_delete": False,
    }
    context.update(extra)
    active_scope = context.get("active") or ""
    if active_scope and active_scope != "settings":
        context["can_delete"] = service.has_scope_data(active_scope)
    if "rows" in context:
        context["rows"] = [_view(row, lang) for row in context["rows"]]
    if "also" in context:
        context["also"] = [_view(row, lang) for row in context["also"]]
    return context


def _view(row: dict, lang: str) -> dict:
    shown = dict(row)
    shown["scope_label"] = scope_label(row["scope"])
    shown["kind_label"] = kind_label(lang, row["kind"])
    shown["when"] = (row.get("updated_at") or "")[:16].replace("T", " ")
    return shown


def _error(lang: str, exc: Exception) -> str:
    key = getattr(exc, "key", "")
    if key:
        return translate(lang, key, **getattr(exc, "params", {}))
    return str(exc)


def _home(scope: str, msg: str = "", layer: str = "") -> str:
    params = []
    if scope and scope not in {"all", ""}:
        params.append("scope=" + quote(scope))
    if layer in {"durable", "daily", "dreams"}:
        params.append("layer=" + quote(layer))
    if msg:
        params.append("msg=" + quote(msg))
    if not params:
        return "/"
    return "/?" + "&".join(params)


def _redirect(url: str, err: str = "", msg: str = "") -> RedirectResponse:
    if msg:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}msg=" + quote(msg)
    if err:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}err=" + quote(err)
    return RedirectResponse(url, status_code=303)
