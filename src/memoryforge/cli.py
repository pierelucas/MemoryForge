from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx
import typer

from memoryforge import __version__
from memoryforge.config import load_config, model_catalog, set_value
from memoryforge.paths import ensure_dirs, log_path, pid_path
from memoryforge.service import get_service, reset

app = typer.Typer(add_completion=False, help="Lokales Gedächtnis für Coding-Agenten.", no_args_is_help=False)
config_app = typer.Typer(help="Konfiguration lesen und setzen.")
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Ohne Befehl: lokalen Dienst sicherstellen und die Adresse anzeigen."""
    if ctx.invoked_subcommand is None:
        cfg = load_config()
        if not _healthy(cfg.server.host, cfg.server.port):
            _spawn(cfg.server.host, cfg.server.port)
            if not _wait_healthy(cfg.server.host, cfg.server.port):
                raise typer.Exit(code=1)
        _print_ready(cfg.server.host, cfg.server.port)


@app.command()
def init() -> None:
    """Legt die Standard-Konfiguration an, falls sie noch fehlt."""
    cfg = load_config()
    if cfg.path and Path(cfg.path).exists():
        typer.echo(f"Konfiguration bleibt: {cfg.path}")
    else:
        cfg.save()
        typer.echo(f"Konfiguration geschrieben: {cfg.path}")
    ensure_dirs()
    typer.echo(f"Datenbank: {get_service().store.path}")


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind-Adresse, Standard 127.0.0.1"),
    port: int | None = typer.Option(None, help="Port, Standard 4737"),
    detach: bool = typer.Option(False, "--detach", help="Im Hintergrund starten"),
) -> None:
    """Startet Web-Oberfläche und HTTP-MCP."""
    cfg = load_config()
    bind = host or cfg.server.host
    chosen = port or cfg.server.port
    if detach:
        if _healthy(bind, chosen):
            _print_ready(bind, chosen)
            return
        _spawn(bind, chosen)
        if not _wait_healthy(bind, chosen):
            raise typer.Exit(code=1)
        _print_ready(bind, chosen)
        return
    os.environ["MEMORYFORGE_BIND_HOST"] = bind
    os.environ.setdefault("MEMORYFORGE_MCP_DETECT", "0")
    import uvicorn

    from memoryforge.server import create_app

    uvicorn.run(create_app(), host=bind, port=chosen, log_level="info")


@app.command()
def stop() -> None:
    """Stoppt den Hintergrunddienst."""
    if _stop():
        typer.echo("Gestoppt.")
    else:
        typer.echo("Es läuft kein MemoryForge-Dienst.")


@app.command()
def ui() -> None:
    """Öffnet die Notiz-Oberfläche im Browser."""
    cfg = load_config()
    if not _healthy(cfg.server.host, cfg.server.port):
        _spawn(cfg.server.host, cfg.server.port)
        if not _wait_healthy(cfg.server.host, cfg.server.port):
            raise typer.Exit(code=1)
    host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    webbrowser.open(f"http://{host}:{cfg.server.port}/")


@app.command()
def mcp() -> None:
    """MCP über stdio. OpenCode startet das im Projektordner."""
    from memoryforge.mcp_server import build_mcp

    build_mcp().run(transport="stdio")


@app.command()
def add(
    text: str = typer.Argument(..., help="Der Fakt. '-' liest von stdin."),
    scope: str | None = typer.Option(None, "--scope", help="global oder project:host/owner/repo"),
    source: str = typer.Option("cli", "--source"),
) -> None:
    """Speichert eine Erinnerung. Im Git-Repo wird der Remote zur Scope, wenn --scope fehlt."""
    if text == "-":
        text = sys.stdin.read()
    try:
        result = get_service().add(text, scope=scope, source=source, detect=scope is None)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if result.get("warning"):
        typer.echo(result["warning"], err=True)
    if result["noop"]:
        typer.echo("Unverändert, das steht schon drin.")
    for row in result["memories"]:
        typer.echo(f"{row['id']}  [{row['scope']}]  {row['text']}")


@app.command()
def search(
    query: str = typer.Argument(...),
    scope: str | None = typer.Option(None, "--scope"),
    limit: int = typer.Option(8, "--limit"),
) -> None:
    """Sucht per Bedeutung und Volltext. Ohne --scope im Repo: Projekt plus global."""
    resolved = scope
    detect = scope is None
    if detect:
        from memoryforge.scope import detect_scope

        found = detect_scope()
        resolved = None if found == "global" else found
    rows = get_service().search(query, scope=resolved, limit=limit)
    if not rows:
        typer.echo("Nichts gefunden.")
        return
    for row in rows:
        score = row.get("score", 0)
        typer.echo(f"{score:0.2f}  {row['id']}  [{row['scope']}]  {row['text']}")


@app.command("list")
def list_memories(
    scope: str | None = typer.Option(None, "--scope"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """Listet aktive Erinnerungen."""
    rows = get_service().list_memories(scope, limit=limit)
    if not rows:
        typer.echo("Keine Erinnerungen.")
        return
    for row in rows:
        mark = "*" if row["pinned"] else " "
        typer.echo(f"{mark} {row['id']}  [{row['scope']}]  {row['text']}")


@app.command()
def forget(memory_id: str = typer.Argument(...)) -> None:
    """Blendet eine Erinnerung aus."""
    try:
        get_service().forget(memory_id)
    except KeyError:
        typer.echo("Unbekannte Id.", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Vergessen: {memory_id}")


@app.command()
def pin(
    memory_id: str = typer.Argument(...),
    off: bool = typer.Option(False, "--off", help="Anheftung lösen"),
) -> None:
    """Heftet eine Erinnerung an die Session-Karte."""
    try:
        row = get_service().pin(memory_id, not off)
    except KeyError:
        typer.echo("Unbekannte Id.", err=True)
        raise typer.Exit(code=1) from None
    state = "angeheftet" if row["pinned"] else "gelöst"
    typer.echo(f"{memory_id} {state}.")


@app.command()
def dream(scope: str | None = typer.Option(None, "--scope")) -> None:
    """Fasst Duplikate zusammen, wenn eine KI konfiguriert und an ist."""
    result = get_service().dream(scope)
    typer.echo(result["message"])
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command()
def reembed() -> None:
    """Rechnet alle Vektoren mit dem lokalen Embedding-Modell neu."""
    count = get_service().reembed()
    typer.echo(f"{count} Erinnerungen neu eingebettet.")


@app.command()
def doctor() -> None:
    """Zeigt Pfade, Zähler und ob die KI an ist."""
    cfg = load_config()
    service = get_service()
    host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    typer.echo(f"Version      {__version__}")
    typer.echo(f"Konfiguration {cfg.path}")
    typer.echo(f"Datenbank    {service.store.path}")
    typer.echo(f"Erinnerungen {service.store.count_active()}")
    typer.echo(f"Embeddings   {service.embedder.name}")
    typer.echo(f"KI           {'an' if cfg.llm.enabled else 'aus'}  {cfg.llm.provider}  {cfg.llm.model}")
    typer.echo(f"API-Basis    {cfg.llm.base_url or '—'}")
    typer.echo(f"Key          {'gesetzt' if cfg.llm.api_key else 'fehlt'}")
    typer.echo(f"Dienst       {'läuft' if _healthy(cfg.server.host, cfg.server.port) else 'aus'}  http://{host}:{cfg.server.port}/")


@app.command()
def backup(
    output: Path | None = typer.Option(None, "--output", "-o"),
    without_secrets: bool = typer.Option(False, "--without-secrets", help="API-Key nicht mitpacken"),
) -> None:
    """Schreibt ein ZIP für den Umzug auf einen anderen Rechner."""
    from memoryforge.backup import create_backup

    dest = output or Path.cwd() / f"memoryforge-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    create_backup(dest, include_secrets=not without_secrets)
    typer.echo(f"Backup: {dest.resolve()}")
    if not without_secrets and load_config().llm.api_key:
        typer.echo("Das ZIP enthält den API-Key im Klartext.")


@app.command()
def restore(archive: Path = typer.Argument(..., help="memoryforge-backup-....zip")) -> None:
    """Ersetzt lokale Konfiguration und Datenbank durch ein Backup."""
    from memoryforge.backup import BackupError, restore_backup

    _stop()
    reset()
    try:
        info = restore_backup(archive)
    except BackupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wiederhergestellt: {info['config']}")
    typer.echo(f"Datenbank: {info['memories_db']}")
    if info.get("warning"):
        typer.echo(info["warning"])
    typer.echo("Starte neu mit: memoryforge")


@config_app.command("show")
def config_show() -> None:
    """Zeigt die Konfiguration. Der API-Key ist maskiert."""
    cfg = load_config()
    data = cfg.masked()
    typer.echo(f"Datei {cfg.path}")
    for section, values in data.items():
        typer.echo(f"[{section}]")
        for key, value in values.items():
            typer.echo(f"  {key} = {value}")


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Setzt ein Feld, zum Beispiel llm.model deepseek-v4-pro oder llm.enabled true."""
    cfg = load_config()
    try:
        set_value(cfg, key, value)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    reset()
    typer.echo(f"{key} = {value}")


@config_app.command("models")
def config_models() -> None:
    """Listet die mitgelieferten Modellnamen."""
    for row in model_catalog():
        typer.echo(f"{row['provider']:10}  {row['id']:22}  {row['label']}")
    typer.echo("Eigene ID: memoryforge config set llm.model <id>")


@app.command("install-service")
def install_service() -> None:
    """Richtet einen Benutzerdienst ein (systemd oder launchd)."""
    exe = _executable()
    if sys.platform.startswith("linux"):
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit = unit_dir / "memoryforge.service"
        unit.write_text(
            "\n".join(
                [
                    "[Unit]",
                    "Description=MemoryForge local memory",
                    "After=default.target",
                    "",
                    "[Service]",
                    f"ExecStart={exe} serve",
                    "Restart=on-failure",
                    "",
                    "[Install]",
                    "WantedBy=default.target",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        typer.echo(f"Unit geschrieben: {unit}")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "memoryforge"], check=False)
        return
    if sys.platform == "darwin":
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True, exist_ok=True)
        plist = plist_dir / "com.memoryforge.plist"
        plist.write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.memoryforge</string>
  <key>ProgramArguments</key>
  <array><string>{exe}</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
""",
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "unload", str(plist)], check=False)
        subprocess.run(["launchctl", "load", str(plist)], check=False)
        typer.echo(f"LaunchAgent geschrieben: {plist}")
        return
    typer.echo("Automatischer Start ist hier nicht eingerichtet. Starte mit: memoryforge serve")


def _executable() -> str:
    found = shutil_which("memoryforge")
    return found or f"{sys.executable} -m memoryforge"


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _connect_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _healthy(host: str, port: int) -> bool:
    try:
        response = httpx.get(f"http://{_connect_host(host)}:{port}/api/health", timeout=0.5)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        return response.json().get("status") == "ok"
    except ValueError:
        return False


def _wait_healthy(host: str, port: int) -> bool:
    for _ in range(40):
        if _healthy(host, port):
            return True
        time.sleep(0.25)
    typer.echo(f"Dienst nicht erreichbar. Log: {log_path()}", err=True)
    return False


def _spawn(host: str, port: int) -> None:
    ensure_dirs()
    log = open(log_path(), "ab")
    cmd = [sys.executable, "-m", "memoryforge", "serve", "--host", host, "--port", str(port)]
    kwargs: dict = {
        "stdout": log,
        "stderr": log,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    pid_path().write_text(str(proc.pid), encoding="utf-8")


def _stop() -> bool:
    path = pid_path()
    if not path.exists():
        return False
    raw = path.read_text(encoding="utf-8").strip()
    path.unlink(missing_ok=True)
    if not raw.isdigit():
        return False
    pid = int(raw)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def _print_ready(host: str, port: int) -> None:
    shown = _connect_host(host)
    typer.echo(f"MemoryForge {__version__}  http://{shown}:{port}/")
    typer.echo(f"MCP für andere Rechner     http://{shown}:{port}/mcp")
    typer.echo("OpenCode auf diesem Rechner: memoryforge mcp  (stdio, erkennt das Git-Repo)")
