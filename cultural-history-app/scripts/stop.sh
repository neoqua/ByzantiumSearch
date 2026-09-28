#!/usr/bin/env bash
# Stop the Cultural History Analyzer stack (Linux / macOS).
#
#   scripts/stop.sh             Stop and remove containers. SQLite data in ./data
#                               and the SearXNG settings volume are kept.
#   scripts/stop.sh --volumes   Also remove the SearXNG volume (./data is never touched).
#
# Also terminates a host-mode uvicorn ("app.main:app") if one is still running.
# LM Studio is not managed by this script.
set -euo pipefail

cd "$(dirname "$0")/.."

VOLUMES=0
for arg in "$@"; do
    case "$arg" in
        --volumes) VOLUMES=1 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*" >&2; }

# Host-mode uvicorn started by scripts/start.sh --host: only *our* user's
# process on port 8000. Other projects may run "uvicorn app.main:app" too.
UVICORN_RE='uvicorn app\.main:app.*--port 8000'
find_uvicorn() { pgrep -u "$(id -u)" -f "$UVICORN_RE" 2>/dev/null || true; }

if [ -n "$(find_uvicorn)" ]; then
    log "Stopping host-mode uvicorn (port 8000)"
    pkill -TERM -u "$(id -u)" -f "$UVICORN_RE" || true
    for _ in 1 2 3 4 5; do
        [ -z "$(find_uvicorn)" ] && break
        sleep 1
    done
    if [ -n "$(find_uvicorn)" ]; then
        pkill -KILL -u "$(id -u)" -f "$UVICORN_RE" || true
    fi
fi

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    warn "Docker is not available; nothing to stop on the container side."
    exit 0
fi

log "Stopping containers"
if [ "$VOLUMES" = 1 ]; then
    docker compose down --volumes
else
    docker compose down
fi

log "Done. SQLite data kept in ./data"
