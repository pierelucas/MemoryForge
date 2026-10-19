#!/usr/bin/env bash
# MemoryForge installieren, optional aus einem Backup wiederherstellen.
#   ./install.sh
#   ./install.sh --yes --service
#   ./install.sh --restore memoryforge-backup-20261019-1504.zip
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YES=0
SERVICE=0
RESTORE=""

usage() {
  cat <<'EOF'
Verwendung: ./install.sh [--yes] [--service] [--restore datei.zip]

  --yes        keine Fragen stellen
  --service    Benutzerdienst einrichten (systemd oder launchd)
  --restore    Konfiguration und Datenbank aus einem MemoryForge-ZIP übernehmen
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --service) SERVICE=1; shift ;;
    --restore)
      RESTORE="${2:-}"
      if [[ -z "${RESTORE}" ]]; then
        echo "Pfad zum ZIP fehlt." >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekanntes Argument: $1" >&2; usage; exit 1 ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "Installiere uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv liegt nicht im PATH. Öffne eine neue Shell oder nimm ${HOME}/.local/bin in den PATH." >&2
  exit 1
fi

echo "Installiere memoryforge…"
uv tool install --force --from "${ROOT}" memoryforge
hash -r || true

if [[ -n "${RESTORE}" ]]; then
  if [[ ! -f "${RESTORE}" ]]; then
    echo "Backup nicht gefunden: ${RESTORE}" >&2
    exit 1
  fi
  memoryforge restore "${RESTORE}"
else
  memoryforge init
  if [[ "${YES}" -eq 0 && -t 0 ]]; then
    read -r -p "KI-Extraktion jetzt einrichten? [j/N] " ANSWER || true
    case "${ANSWER:-}" in
      j|J|y|Y)
        read -r -p "Anbieter [deepseek/openai/custom] (deepseek): " PROVIDER || true
        PROVIDER="${PROVIDER:-deepseek}"
        read -r -p "Modell-ID (deepseek-flash): " MODEL || true
        MODEL="${MODEL:-deepseek-flash}"
        read -r -p "API-Basis (leer = Standard des Anbieters): " BASE || true
        read -r -s -p "API-Key: " KEY || true
        echo
        memoryforge config set llm.enabled true
        memoryforge config set llm.provider "${PROVIDER}"
        memoryforge config set llm.model "${MODEL}"
        if [[ -n "${BASE}" ]]; then
          memoryforge config set llm.base_url "${BASE}"
        fi
        if [[ -n "${KEY}" ]]; then
          memoryforge config set llm.api_key "${KEY}"
        fi
        ;;
    esac
  fi
fi

if [[ "${SERVICE}" -eq 1 ]]; then
  memoryforge install-service
fi

cat <<'EOF'

MemoryForge ist installiert.

  memoryforge            Dienst starten und Adresse anzeigen
  memoryforge ui         Notizbuch im Browser
  memoryforge doctor     Pfade und KI-Status

OpenCode, lokal, im Projekt (empfohlen, erkennt das Git-Repo):

  {
    "mcp": {
      "servers": {
        "memoryforge": {
          "type": "local",
          "command": ["memoryforge", "mcp"]
        }
      }
    }
  }

Andere Rechner, derselbe Dienst:

  http://127.0.0.1:4737/mcp

Umzug: memoryforge backup  und auf dem neuen Rechner  ./install.sh --restore datei.zip
EOF
