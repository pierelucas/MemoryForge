#!/usr/bin/env bash
# MemoryForge entfernen.
#   ./uninstall.sh                 Dienst und Kommando entfernen, Daten bleiben
#   ./uninstall.sh --yes           ohne Rückfrage
#   ./uninstall.sh --yes --purge   zusätzlich Konfiguration und Datenbank löschen
set -euo pipefail

YES=0
PURGE=0

usage() {
  cat <<'EOF'
Verwendung: ./uninstall.sh [--yes] [--purge]

  --yes      keine Frage stellen
  --purge    zusätzlich Konfiguration und Datenbank löschen

Ohne --purge bleiben ~/.config/memoryforge und ~/.local/share/memoryforge
erhalten. uv selbst und die OpenCode-Konfiguration werden nicht angefasst.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --purge) PURGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekanntes Argument: $1" >&2; usage; exit 1 ;;
  esac
done

config_dir="${MEMORYFORGE_CONFIG_DIR:-}"
if [[ -z "${config_dir}" ]]; then
  config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/memoryforge"
fi

data_dir="${MEMORYFORGE_DATA_DIR:-}"
if [[ -z "${data_dir}" ]]; then
  data_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/memoryforge"
fi

if [[ "${YES}" -eq 0 ]]; then
  if [[ "${PURGE}" -eq 1 ]]; then
    read -r -p "Dienst, Kommando, Konfiguration und Datenbank entfernen? [j/N] " ANSWER || true
  else
    read -r -p "Dienst und Kommando entfernen? Konfiguration und Datenbank bleiben. [j/N] " ANSWER || true
  fi
  case "${ANSWER:-}" in
    j|J|y|Y) ;;
    *) echo "Abgebrochen."; exit 0 ;;
  esac
fi

stop_process() {
  if command -v memoryforge >/dev/null 2>&1; then
    memoryforge stop >/dev/null 2>&1 || true
  fi
  local pidfile="${data_dir}/memoryforge.pid"
  [[ -f "${pidfile}" ]] || return 0
  local pid
  pid="$(tr -dc '0-9' < "${pidfile}" || true)"
  rm -f "${pidfile}"
  [[ -n "${pid}" ]] || return 0
  # Never kill a process that merely reused a stale pid.
  if [[ -r "/proc/${pid}/cmdline" ]] && ! tr '\0' ' ' < "/proc/${pid}/cmdline" | grep -q memoryforge; then
    return 0
  fi
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 50); do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -9 "${pid}" 2>/dev/null || true
}

if [[ "$(uname -s)" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now memoryforge >/dev/null 2>&1 || true
  rm -f "${HOME}/.config/systemd/user/memoryforge.service"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  plist="${HOME}/Library/LaunchAgents/com.memoryforge.plist"
  if [[ -f "${plist}" ]]; then
    launchctl unload "${plist}" >/dev/null 2>&1 || true
    rm -f "${plist}"
  fi
fi

stop_process

if command -v uv >/dev/null 2>&1; then
  uv tool uninstall memoryforge >/dev/null 2>&1 || true
fi

if [[ "${PURGE}" -eq 1 ]]; then
  rm -rf "${config_dir}" "${data_dir}"
  data_note="gelöscht"
else
  data_note="behalten: ${config_dir} und ${data_dir}"
fi

cat <<EOF
MemoryForge ist entfernt.

  Dienst      gestoppt und abgemeldet
  Kommando    deinstalliert
  Daten       ${data_note}

Der MCP-Eintrag in der OpenCode-Konfiguration bleibt bestehen. Entferne ihn
dort von Hand oder in OpenCode unter /mcps, sonst startet OpenCode ein
fehlendes Kommando.

uv wurde nicht deinstalliert.
EOF
