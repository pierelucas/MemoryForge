from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from memoryforge import __version__
from memoryforge.config import KIND_LABELS, PROVIDERS, known_model, load_config, model_catalog
from memoryforge.scope import scope_label
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
    def index(request: Request, q: str = "", scope: str = "", msg: str = "", err: str = ""):
        service = get_service()
        active = scope or ""
        also: list = []
        if q.strip():
            rows = service.search(
                q.strip(),
                scope=active or None,
                limit=40,
                include_global=bool(active) and active != "global",
            )
        elif active and active != "global":
            rows = service.list_memories(active, limit=80)
            also = service.list_memories("global", limit=40)
        else:
            rows = service.list_memories(active or None, limit=80)
        return templates.TemplateResponse(
            request,
            "index.html",
            _page(request, rows=rows, also=also, q=q, active=scope, msg=msg, err=err),
        )

    @app.post("/memories")
    def create_memory(text: str = Form(...), scope: str = Form(""), scope_custom: str = Form("")):
        service = get_service()
        chosen = (scope_custom or scope or "global").strip() or "global"
        try:
            result = service.add(text, scope=chosen, source="ui", detect=False)
        except ValueError as exc:
            return _redirect("/", err=str(exc))
        if not result["memories"] and result["noop"]:
            return _redirect(_home(chosen, "War schon gespeichert."))
        return _redirect(_home(chosen, "Gespeichert."))

    @app.post("/memories/{memory_id}")
    def edit_memory(memory_id: str, text: str = Form(...), scope: str = Form("")):
        try:
            row = get_service().update(memory_id, text)
        except KeyError:
            raise HTTPException(status_code=404) from None
        except ValueError as exc:
            return _redirect(_home(scope, ""), err=str(exc))
        return _redirect(_home(scope or row["scope"], "Aktualisiert."))

    @app.get("/memories/{memory_id}/forget", response_class=HTMLResponse)
    def forget_confirm(request: Request, memory_id: str):
        row = get_service().store.get(memory_id)
        if row is None or row["forgotten"]:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request,
            "forget.html",
            _page(request, memory=_view(row), active=row["scope"]),
        )

    @app.post("/memories/{memory_id}/forget")
    def forget_memory(memory_id: str):
        try:
            row = get_service().store.get(memory_id)
            get_service().forget(memory_id)
        except KeyError:
            raise HTTPException(status_code=404) from None
        scope = row["scope"] if row else ""
        return _redirect(_home(scope, "Vergessen."))

    @app.post("/memories/{memory_id}/pin")
    def pin_memory(memory_id: str, scope: str = Form("")):
        row = get_service().store.get(memory_id)
        if row is None:
            raise HTTPException(status_code=404)
        get_service().pin(memory_id, not row["pinned"])
        return _redirect(_home(scope or row["scope"]))

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
                known=known_model(cfg.llm.model),
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
    ):
        cfg = load_config()
        cfg.llm.enabled = enabled == "1"
        if provider not in PROVIDERS:
            provider = "custom"
        cfg.llm.provider = provider
        custom = model_custom.strip()
        chosen = custom or model_choice.strip() or cfg.llm.model
        if chosen == "__custom__":
            chosen = custom or cfg.llm.model
        cfg.llm.model = chosen
        url = base_url.strip()
        if not url and provider in PROVIDERS and PROVIDERS[provider]["base_url"]:
            url = PROVIDERS[provider]["base_url"]
        cfg.llm.base_url = url
        cfg.llm.thinking = thinking == "1"
        if clear_key == "1":
            cfg.llm.api_key = ""
        elif api_key.strip():
            cfg.llm.api_key = api_key.strip()
        cfg.save()
        return _redirect("/settings?msg=" + quote("Gespeichert."))

    @app.post("/settings/test")
    def test_settings():
        service = get_service()
        if not service.cfg.llm.enabled:
            return _redirect("/settings?err=" + quote("KI ist aus."))
        try:
            result = service.llm.ping()
        except Exception as exc:  # noqa: BLE001 — show the provider error on the settings page
            message = str(exc)
            return _redirect("/settings?err=" + quote(message[:240]))
        model = result.get("model") or service.cfg.llm.model
        return _redirect("/settings?msg=" + quote(f"Erreichbar, Modell {model}."))

    @app.post("/dream")
    def dream(scope: str = Form("")):
        result = get_service().dream(scope or None)
        target = "/settings" if not scope else _home(scope)
        key = "msg" if result.get("ok") else "err"
        return _redirect(f"{target}?{key}=" + quote(result.get("message") or "Fertig."))

    @app.post("/backup")
    def backup_now(secrets: str = Form("1")):
        from memoryforge.backup import create_backup
        from memoryforge.paths import data_dir

        dest = data_dir() / "memoryforge-backup.zip"
        create_backup(dest, include_secrets=secrets == "1")
        return FileResponse(dest, filename="memoryforge-backup.zip", media_type="application/zip")

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
    scopes = service.store.scopes()
    context = {
        "request": request,
        "version": __version__,
        "scopes": [
            {
                "scope": row["scope"],
                "count": row["count"],
                "label": scope_label(row["scope"]),
            }
            for row in scopes
        ],
        "total": service.store.count_active(),
        "kind_labels": KIND_LABELS,
    }
    context.update(extra)
    if "rows" in context:
        context["rows"] = [_view(row) for row in context["rows"]]
    if "also" in context:
        context["also"] = [_view(row) for row in context["also"]]
    return context


def _view(row: dict) -> dict:
    shown = dict(row)
    shown["scope_label"] = scope_label(row["scope"])
    shown["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    shown["when"] = (row.get("updated_at") or "")[:16].replace("T", " ")
    return shown


def _home(scope: str, msg: str = "") -> str:
    params = []
    if scope and scope not in {"all", ""}:
        params.append("scope=" + quote(scope))
    if msg:
        params.append("msg=" + quote(msg))
    if not params:
        return "/"
    return "/?" + "&".join(params)


def _redirect(url: str, err: str = "") -> RedirectResponse:
    if err:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}err=" + quote(err)
    return RedirectResponse(url, status_code=303)
