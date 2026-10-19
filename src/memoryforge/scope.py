from __future__ import annotations

import re
import subprocess
from pathlib import Path


def normalize_remote(url: str) -> str:
    text = url.strip()
    text = re.sub(r"\.git$", "", text)
    if text.startswith("git@"):
        host_path = text.split("@", 1)[1]
        if ":" in host_path:
            host, path = host_path.split(":", 1)
            return f"{host}/{path}"
    match = re.match(r"https?://([^/]+)/(.+)", text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return text


def normalize_scope(scope: str | None) -> str:
    if scope is None:
        return ""
    text = scope.strip()
    if text.lower() in {"", "all", "*"}:
        return ""
    if text.lower() == "global":
        return "global"
    if text.startswith("project:"):
        rest = text.split(":", 1)[1].strip()
        if rest.startswith("git@") or rest.startswith("http://") or rest.startswith("https://"):
            rest = normalize_remote(rest)
        return "project:" + rest.removesuffix(".git")
    if text.startswith("git@") or text.startswith("http://") or text.startswith("https://"):
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
