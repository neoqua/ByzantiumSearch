# Deployment Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the app so it runs on a fresh machine (Windows/Mac + Docker Desktop + LM Studio on host) with a single `docker compose up -d --build`, plus documented host-mode (venv/uvicorn) instructions for debugging.

**Architecture:** Add a `Dockerfile` + `.dockerignore` so the FastAPI app builds into an image; extend the existing `docker-compose.yml` with an `app` service that talks to `searxng` over the compose network and to LM Studio on the host via `host.docker.internal`; persist the SQLite DB via a `./data:/app/data` volume; move machine-specific env out of the repo into `.env.example`; write a `README.md` runbook covering both modes.

**Tech Stack:** Docker, Docker Compose, Python 3.13-slim image, uvicorn, existing FastAPI app.

## Global Constraints

- App must run on a machine with Docker Desktop (Windows/Mac) and LM Studio on the host, port 1234
- LM Studio host access from container uses `host.docker.internal` (Docker Desktop provides it natively)
- SearXNG runs as a compose service; app reaches it at `http://searxng:8080` (compose network), host access at `http://localhost:8888`
- `.env` must NOT be baked into the image; env comes from `docker-compose.yml` `environment:` (compose env overrides `load_dotenv`, which never overwrites existing env vars)
- SQLite DB persists on the host via `./data:/app/data`
- `DATABASE_URL=sqlite+aiosqlite:///./data/app.db` resolves to `/app/data/app.db` (WORKDIR `/app`)
- No secrets or machine-specific URLs committed: `.env` is removed from git tracking, `.env.example` committed instead
- Host mode needs no `.env`: `config.py` defaults already point at `localhost:8888` / `localhost:1234`
- Verify locally with `.\venv\Scripts\python.exe` (pytest and aiohttp hang on this machine — do not run them; do not run `uvicorn app.main:app` here either)
- Docker CLI is NOT installed on the dev machine — image build / `docker compose config` verification happens on the target machine; locally validate YAML with the venv's PyYAML
- One commit per task, message style matches repo (`feat:` / `fix:` / `docs:`)

---

### Task 1: Containerize the app — Dockerfile, .dockerignore, compose `app` service

**Files:**
- Create: `cultural-history-app/Dockerfile`
- Create: `cultural-history-app/.dockerignore`
- Modify: `cultural-history-app/docker-compose.yml`

**Interfaces:**
- Consumes: existing `app/` package (imports at runtime), `requirements.txt`, `config.py` env vars `SEARXNG_BASE_URL`, `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL`, `DATABASE_URL`
- Produces: `Dockerfile` at repo root of `cultural-history-app/`, compose service named `app` reachable at host port 8000

- [ ] **Step 1: Create `cultural-history-app/Dockerfile`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `cultural-history-app/.dockerignore`**

```
venv/
__pycache__/
*.pyc
data/
.env
.git
.gitignore
tests/
docs/
```

- [ ] **Step 3: Modify `cultural-history-app/docker-compose.yml`**

Replace the whole file with:

```yaml
version: '3.8'

services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8888:8080"
    volumes:
      - ./searxng/settings.yml:/etc/searxng/settings.yml:ro
      - searxng-data:/etc/searxng
    environment:
      - SEARXNG_BASE_URL=http://localhost:8888
    restart: unless-stopped

  app:
    build: .
    container_name: cultural-history-app
    ports:
      - "8000:8000"
    environment:
      - SEARXNG_BASE_URL=http://searxng:8080
      - LM_STUDIO_BASE_URL=http://host.docker.internal:1234
      - LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
      - DATABASE_URL=sqlite+aiosqlite:///./data/app.db
    volumes:
      - ./data:/app/data
    depends_on:
      - searxng
    restart: unless-stopped

volumes:
  searxng-data:
```

- [ ] **Step 4: Validate the compose file YAML locally**

Run (from `cultural-history-app/`):
`.\venv\Scripts\python.exe -c "import yaml, pathlib; d = yaml.safe_load(pathlib.Path('docker-compose.yml').read_text(encoding='utf-8')); assert 'app' in d['services'] and 'searxng' in d['services']; assert d['services']['app']['build'] == '.'; assert 'LM_STUDIO_BASE_URL=http://host.docker.internal:1234' in d['services']['app']['environment']; assert 'SEARXNG_BASE_URL=http://searxng:8080' in d['services']['app']['environment']; print('compose OK')"`

Expected: prints `compose OK`

- [ ] **Step 5: Verify the Dockerfile references valid paths**

Run (from `cultural-history-app/`):
`Get-Content Dockerfile, .dockerignore`
Expected: paths `requirements.txt` and `app ./app` exist relative to `cultural-history-app/`; `.dockerignore` excludes `venv/`, `data/`, `.env`, `tests/`

- [ ] **Step 6: Commit**

```bash
git add cultural-history-app/Dockerfile cultural-history-app/.dockerignore cultural-history-app/docker-compose.yml
git commit -m "feat: containerize app and add compose app service"
```

---

### Task 2: Env hygiene — .env.example, .gitignore, untrack .env

**Files:**
- Create: `cultural-history-app/.env.example`
- Modify: `cultural-history-app/.gitignore`

**Interfaces:**
- Consumes: compose `environment:` values from Task 1 (single source of truth for Docker mode); `config.py` defaults for host mode
- Produces: `.env.example` documenting both modes; `.env` removed from git index (stays on disk, ignored)

- [ ] **Step 1: Create `cultural-history-app/.env.example`**

```
# Copy to .env ONLY if you need to override defaults. Do not commit .env.
#
# Docker mode (docker compose up -d --build): values come from the
# `environment:` section in docker-compose.yml — no .env file needed.
#
# Host mode (uvicorn on this machine, SearXNG on localhost:8888,
# LM Studio on localhost:1234): config.py defaults already match, so
# no .env file is needed either. Uncomment and edit only to override:

# DATABASE_URL=sqlite+aiosqlite:///./data/app.db
# SEARXNG_BASE_URL=http://localhost:8888
# LM_STUDIO_BASE_URL=http://localhost:1234
# LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
```

- [ ] **Step 2: Append `.env` to `cultural-history-app/.gitignore`**

`cultural-history-app/.gitignore` must contain exactly:

```
venv/
__pycache__/
*.pyc
data/
.env
```

- [ ] **Step 3: Untrack `.env` without deleting it**

Run (from repo root):
`git rm --cached cultural-history-app/.env`
Then: `git status --short`
Expected: `.env` no longer listed as tracked; file still exists on disk

- [ ] **Step 4: Verify nothing else tracks `.env`**

Run (from repo root):
`git ls-files | Select-String "\.env"`
Expected: only `.env.example` listed, no `.env`

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/.env.example cultural-history-app/.gitignore
git commit -m "fix: untrack .env, add .env.example and gitignore entry"
```

---

### Task 3: Deployment runbook — README.md + AGENTS.md

**Files:**
- Create: `cultural-history-app/README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: compose service names/URLs from Task 1, env-mode rules from Task 2
- Produces: `README.md` with Docker-mode and host-mode run instructions; `AGENTS.md` deployment section

- [ ] **Step 1: Create `cultural-history-app/README.md`**

```markdown
# Cultural History Analysis App

FastAPI web service: searches travel blogs for mentions of cultural/historical
objects via SearXNG, analyzes relevance with Llama 3.1-8B (LM Studio), generates
reports.

## Requirements

- Docker Desktop (Windows/Mac) — for SearXNG and the app container
- LM Studio running on the host, port 1234, model `meta-llama-3.1-8b-instruct`
  (set `LM_STUDIO_MODEL` if different)

## Docker mode (recommended)

1. Start LM Studio and load the model (`http://localhost:1234/v1/models` should respond).
2. From `cultural-history-app/`:

   `docker compose up -d --build`

3. Open `http://localhost:8000` in a browser.
4. SearXNG is also exposed at `http://localhost:8888` (optional).

Stopping: `docker compose down`. SQLite data persists in `./data/`.

Notes:
- The app container reaches LM Studio on the host via `host.docker.internal:1234`.
- Rebuild after Python-code changes: `docker compose up -d --build`.
- No `.env` needed — configuration comes from `docker-compose.yml`
  `environment:` (see `.env.example`).

## Host mode (debugging, no container for the app)

Requires Python 3.13 + the venv already set up, SearXNG up via Docker:

`docker compose up -d searxng`

then, from `cultural-history-app/`:

```
.\venv\Scripts\python.exe -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

`config.py` defaults already point to `localhost:8888` (SearXNG) and
`localhost:1234` (LM Studio); create a `.env` only to override (see `.env.example`).
Open `http://localhost:8000`.

## Tests

Test logic is verified manually via `python -c` scripts — `pytest` hangs on
Windows/Python 3.13 (see AGENTS.md Known issues).
```

- [ ] **Step 2: Verify README file**

Run: `Get-Content cultural-history-app/README.md`
Expected: all four sections present (Requirements, Docker mode, Host mode, Tests); commands match compose service names and ports from Task 1

- [ ] **Step 3: Add a deployment section to `AGENTS.md`**

Insert a new section `## Deployment` (after the `## How to work` section) with:

```markdown
## Deployment

- Docker mode: `cd cultural-history-app; docker compose up -d --build` — starts SearXNG + app; app at :8000, SearXNG at :8888
- App container reaches LM Studio on the host via `host.docker.internal:1234`, SearXNG via `http://searxng:8080` (compose network)
- SQLite persists via `./data:/app/data` volume
- Host mode: `docker compose up -d searxng` + `uvicorn app.main:app --reload` (config.py defaults point to localhost)
- No `.env` needed in either mode; `.env.example` documents overrides; do not commit `.env`
- Docker CLI is absent on the dev machine — Docker artifacts are verified on the target machine (compose YAML validated locally via venv PyYAML)
```

- [ ] **Step 4: Commit**

```bash
git add cultural-history-app/README.md AGENTS.md
git commit -m "docs: add deployment runbook and README"
```

---

### Task 4: Final review pass

**Files:**
- None (read-only verification)

**Interfaces:**
- Consumes: everything from Tasks 1-3

- [ ] **Step 1: Re-run the compose YAML validation from Task 1 Step 4**

Expected: prints `compose OK`

- [ ] **Step 2: Confirm git state**

Run (from repo root): `git status --short` and `git log --oneline -5`
Expected: working tree clean except `.superpowers/` (untracked, by design); last 3 commits are the deployment tasks

- [ ] **Step 3: Confirm no secrets committed**

Run: `git ls-files | Select-String "\.env"`
Expected: only `.env.example`

---

## Self-Review

**Spec coverage:** Design-approved requirements map 1:1 — Dockerfile+compose app service (Task 1), `.env.example` + untrack `.env` (Task 2), README both modes (Task 3), AGENTS.md deploy section (Task 3), volume persistence and `host.docker.internal` wiring (Task 1). No gaps.

**Placeholder scan:** No TBD/TODO; every step has concrete file content or exact commands.

**Type consistency:** Service name `app`, URLs `http://searxng:8080` and `http://host.docker.internal:1234`, and volume `./data:/app/data` are identical across Tasks 1, 2, and 3. `.env.example` overrides match `config.py` variable names exactly (`DATABASE_URL`, `SEARXNG_BASE_URL`, `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL`).
