#!/usr/bin/env bash
# Start the Cultural History Analyzer stack (Linux / macOS).
#
#   scripts/start.sh              Docker mode: app + SearXNG + OpenSERP in containers
#   scripts/start.sh --host       Host mode:   SearXNG + OpenSERP in containers,
#                                              app via uvicorn from ./venv (foreground, Ctrl+C to stop)
#   scripts/start.sh --no-build   Docker mode without rebuilding the app image
#
# LM Studio is not managed by this script: start it on the host (port 1234)
# or configure a remote LLM provider in the web UI.
set -euo pipefail

cd "$(dirname "$0")/.."

MODE=docker
BUILD=1
for arg in "$@"; do
    case "$arg" in
        --host) MODE=host ;;
        --no-build) BUILD=0 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

APP_URL="http://localhost:8000"
SEARXNG_URL="http://localhost:8888"
OPENSERP_URL="http://localhost:7000"
LMSTUDIO_URL="http://localhost:1234/v1/models"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

http_ok() { curl -fsS -o /dev/null --max-time 3 "$1" 2>/dev/null; }

wait_http() {
    local url="$1" name="$2" timeout="${3:-60}" i=0
    printf '    waiting for %s ' "$name"
    while ! http_ok "$url"; do
        i=$((i + 1))
        if [ "$i" -ge "$timeout" ]; then
            printf '\n'
            warn "$name did not answer at $url within ${timeout}s (check: docker compose logs)"
            return 1
        fi
        printf '.'
        sleep 1
    done
    printf ' ok\n'
}

ensure_searxng_secret() {
    if [ -z "${SEARXNG_SECRET:-}" ] && [ -f .env ]; then
        line="$(grep '^SEARXNG_SECRET=' .env | tail -1 || true)"
        SEARXNG_SECRET="${line#SEARXNG_SECRET=}"
        SEARXNG_SECRET="${SEARXNG_SECRET%$'\r'}"
    fi
    if [ -z "${SEARXNG_SECRET:-}" ]; then
        SEARXNG_SECRET="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"
        [ -n "$SEARXNG_SECRET" ] || die "cannot generate SEARXNG_SECRET"
        printf 'SEARXNG_SECRET=%s\n' "$SEARXNG_SECRET" >> .env
        log "Wrote SEARXNG_SECRET into .env (gitignored)"
    fi
    export SEARXNG_SECRET
}

command -v docker >/dev/null 2>&1 || die "docker not found. Install Docker Engine / Docker Desktop first."
docker info >/dev/null 2>&1 || die "Docker daemon is not running (or current user has no access). Start Docker and retry."
command -v curl >/dev/null 2>&1 || die "curl not found (needed for health checks)."

ensure_searxng_secret

if http_ok "$LMSTUDIO_URL"; then
    log "LM Studio detected at $LMSTUDIO_URL"
else
    warn "LM Studio is not answering at $LMSTUDIO_URL. Start its Local Server, or select a remote LLM provider in the UI."
fi

if [ "$MODE" = docker ]; then
    log "Starting SearXNG, OpenSERP and app (Docker mode)"
    if [ "$BUILD" = 1 ]; then
        docker compose up -d --build
    else
        docker compose up -d
    fi
    wait_http "$APP_URL/" "app" 90 || true
    wait_http "$OPENSERP_URL/health" "OpenSERP" 30 || true
    wait_http "$SEARXNG_URL/" "SearXNG" 60 || true
    echo
    docker compose ps
    echo
    log "Open $APP_URL"
    echo "    SearXNG:  $SEARXNG_URL"
    echo "    OpenSERP: $OPENSERP_URL"
    echo "    Logs:     docker compose logs -f app"
    echo "    Stop:     scripts/stop.sh"
else
    log "Starting SearXNG and OpenSERP (host mode)"
    docker compose up -d searxng openserp
    wait_http "$OPENSERP_URL/health" "OpenSERP" 30 || true
    wait_http "$SEARXNG_URL/" "SearXNG" 60 || true

    PY=""
    for candidate in venv/bin/python .venv/bin/python; do
        if [ -x "$candidate" ]; then PY="$candidate"; break; fi
    done
    if [ -z "$PY" ]; then
        log "No Linux venv found — creating ./venv and installing requirements"
        command -v python3 >/dev/null 2>&1 || die "python3 not found."
        python3 -m venv venv
        venv/bin/python -m pip install --quiet --upgrade pip
        venv/bin/python -m pip install --quiet -r requirements.txt
        PY=venv/bin/python
    fi

    echo
    log "Starting app with uvicorn (Ctrl+C stops the app; containers keep running — use scripts/stop.sh)"
    echo "    Open $APP_URL"
    echo
    exec "$PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
fi
