from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

_REMOTE_SCHEMES = {"http", "https", "ssh", "git", "git+ssh"}


def _clean_path(path: str) -> str:
    cleaned = re.sub(r"/+", "/", path.strip()).strip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[: -len(".git")].rstrip("/")
    return cleaned


def _join(host: str, path: str) -> str:
    host = host.strip().lower()
    cleaned = _clean_path(path)
    return f"{host}/{cleaned}" if cleaned else host


def normalize_remote(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if "://" not in text:
        # git@host:path and user:secret@host/path both carry credentials.
        if "@" in text:
            text = text.rsplit("@", 1)[1]
        scp = re.match(r"^([^:/\s]+):(.+)$", text)
        if scp:
            return _join(scp.group(1), scp.group(2))
        return _clean_path(text)
    try:
        parsed = urlsplit(text)
    except ValueError:
        return _clean_path(text)
    if parsed.scheme.lower() in _REMOTE_SCHEMES:
        return _join(parsed.hostname or "", parsed.path)
    return _clean_path(text)


def _lower_host(path: str) -> str:
    """Hosts are case-insensitive. GitHub.com and github.com are one scope."""
    head, sep, tail = path.partition("/")
    return head.lower() + sep + tail


def _looks_remote(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith(("git@", "http://", "https://", "ssh://", "git://", "git+ssh://")):
        return True
    return False


def normalize_scope(scope: str | None) -> str:
    if scope is None:
        return ""
    text = scope.strip()
    if text.lower() in {"", "all", "*"}:
        return ""
    if text.lower() == "global":
        return "global"
    if text.lower().startswith("project:"):
        rest = text.split(":", 1)[1].strip()
        if _looks_remote(rest) or "@" in rest:
            rest = normalize_remote(rest)
        cleaned = _lower_host(_clean_path(rest))
        return "project:" + cleaned if cleaned else ""
    if _looks_remote(text):
        return "project:" + normalize_remote(text)
    return text


def detect_scope(cwd: Path | None = None) -> str:
    folder = cwd or Path.cwd()
    try:
        out = subprocess.run(
            ["git", "-C", str(folder), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "global"
    remote = (out.stdout or "").strip()
    if out.returncode != 0 or not remote:
        return "global"
    return "project:" + normalize_remote(remote)


def scope_label(scope: str) -> str:
    if scope == "global":
        return "Global"
    if scope.startswith("project:"):
        rest = scope.split(":", 1)[1]
        name = rest.rstrip("/").split("/")[-1] or rest
        return name
    return scope


def scope_path_label(scope: str) -> str:
    """Full path without the host, so equal repository names stay distinct."""
    if scope == "global":
        return "Global"
    if scope.startswith("project:"):
        rest = scope.split(":", 1)[1].strip("/")
        parts = rest.split("/", 1)
        return parts[1] if len(parts) == 2 and parts[1] else rest
    return scope
