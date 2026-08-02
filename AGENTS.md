# AGENTS.md

## Overview

Cultural History Analysis App — a FastAPI web service that searches travel blogs and reviews for mentions of cultural/historical objects, analyzes relevance via a local LLM (Llama 3.1 through LM Studio), and generates reports.

## Repo layout

- `cultural-history-app/` — Python project (FastAPI + SQLAlchemy async + aiosqlite)
  - `app/` — package: `config.py`, `database.py`, `models.py`, `schemas.py`, `llm.py`, `search.py`, `scraper.py`, `analyzer.py`, `report.py`, `main.py`, `templates/`
  - `tests/` — pytest tests: `test_llm.py`, `test_search.py`, `test_scraper.py`, `test_api.py`, `test_integration.py`
  - `test_tmp.py` — stray junk at project root (untracked `def test_pass(): assert True`); ignore, do not commit
  - `venv/` — Python 3.13 virtual env (already set up)
  - `requirements.txt` — pinned deps
  - `.env` — local dev config (DB, SearXNG, LM Studio URLs)
  - `data/` — gitignored, SQLite DB created at runtime
- `Тревел блоги.docx` — travel blogs source data (Russian)
- `docs/superpowers/` — original spec and plan (spec-driven development artifacts)
- `.superpowers/` — SDD progress ledger (task briefs, reports, review diffs)

## Current state

- `9f959c9` — initial design spec
- `6976cda` — implementation plan
- `a9bd448` — Task 1: scaffolding (config, DB, models, schemas)
- `ce57886` — Task 2: LLM client (`llm.py`, `test_llm.py`)
- `dc2a072` — Task 3: Search module (`app/search.py`, `tests/test_search.py`, dep pins)
- `a378b5a` — Task 4: Scraper (`app/scraper.py`, `tests/test_scraper.py`)
- `723b31c` — Task 5: Analyzer (`app/analyzer.py`)
- `9cfc0bb` + `9bf1fcb` — Task 6: API endpoints (`app/main.py`, `app/report.py`, `tests/test_api.py`)
- `8b6d859` — Task 7: frontend templates (`app/templates/`)
- `97bb114` — Task 8: SearXNG deployment (`docker-compose.yml`, `searxng/settings.yml`)
- `9545476` — Task 9: integration tests (`tests/test_integration.py`)
- `9545476` — Task 10: runtime verification (`data/` DB, uvicorn smoke test)
- `8d38c2f` — final review fix wave (keyword-aware URL cache, task `failed` state, SSE race, DOM XSS, charset-aware scraping, `load_dotenv`, LLM output coercion)

All plan tasks 1–10 complete. `git status` untracked: `.superpowers/` (SDD ledger, self-ignored) and `cultural-history-app/test_tmp.py` (stray junk) — both left uncommitted by design.

## How to work

- `cd cultural-history-app`
- **Do NOT run `python -m pytest`** — it hangs on this machine (see Known issues). The plan in `docs/superpowers/` says to run pytest; skip those steps. Verify with the venv python directly:
  - Pure functions: `.\venv\Scripts\python.exe -c "from app.scraper import extract_text, text_hash; print('OK')"`
  - Async functions needing mocks (httpx/aiohttp): write a throwaway script that monkeypatches `httpx.AsyncClient` — see `C:\Temp\opencode\manual_test_search.py` for a working pattern
  - Imports: `.\venv\Scripts\python.exe -c "from app.config import settings; from app.models import Task; from app.schemas import SearchRequest; print('OK')"`
- Run app: `uvicorn app.main:app --reload`
- Activate venv: `.\venv\Scripts\Activate.ps1` (or call `.\venv\Scripts\python.exe` directly, as above)
- `.env` requires local SearXNG (port 8888) and LM Studio (port 1234) running

## Deployment

- Docker mode: `cd cultural-history-app; docker compose up -d --build` — starts SearXNG + app; app at :8000, SearXNG at :8888
- App container reaches LM Studio on the host via `host.docker.internal:1234`, SearXNG via `http://searxng:8080` (compose network)
- SQLite persists via `./data:/app/data` volume
- Host mode: `docker compose up -d searxng` + `uvicorn app.main:app --reload` (config.py defaults point to localhost)
- No `.env` needed in either mode; `.env.example` documents overrides; do not commit `.env`
- Docker CLI is absent on the dev machine — Docker artifacts are verified on the target machine (compose YAML validated locally via venv PyYAML)

## Architecture notes

- Async throughout: `httpx.AsyncClient` for LLM and SearXNG calls, `aiohttp` for page fetching
- SQLAlchemy async with `aiosqlite` driver
- LLM endpoint: `{LM_STUDIO_BASE_URL}/v1/chat/completions` (OpenAI-compatible)
- LLM temperature=0.1, max_tokens=256 for deterministic fast responses
- Model: `meta-llama-3.1-8b-instruct` (configurable via `.env`)
- Remote LLM providers: the app supports local (LM Studio) and remote LLM providers (Yandex Cloud YandexGPT, OpenAI-compatible) selectable on the start page; connection settings live in browser `localStorage` and are sent per-request; `POST /api/llm/test` validates a connection
- Prompt engineering: strict JSON-only responses, parseable via `_parse_response()`
- DB schema: `tasks`, `results`, `url_cache` tables
- SearXNG client (`app/search.py`): queries format `{object_name}` and `{object_name} {keyword}` with dedup, language=ru-RU; search now expands queries with UGC markers (`отзывы, блог, форум, впечатления`) and sorts results by heuristic source type (UGC first); LLM returns authoritative `source_type`; stop endpoint (`POST /api/tasks/{id}/stop`) marks task `stopped`

## Version pinning

`requirements.txt` has specific bounds to avoid dependency conflicts:
- `httpx<0.28` required by `pytest-httpx<0.36`
- `pytest<9` required by `pytest-httpx<0.36`

## Known issues

- **pytest hangs on Windows/Python 3.13** — any `python -m pytest` invocation stalls at startup (during collection, with pytest-asyncio + pytest-httpx installed), even for pure-sync test files. Run test logic via `python -c` scripts instead; `C:\Temp\opencode\manual_test_search.py` is a working example of the manual-mock pattern.
- **aiohttp import stall (intermittent)** — aiohttp 3.14.3 was observed to hang on import on Python 3.13 Windows, but imports fine on fresh runs (as of this writing). `tests/test_scraper.py` deliberately imports only the pure functions (`extract_text`, `text_hash`) to stay safe; the async functions (`fetch_page_text`, `fetch_and_analyze`) remain effectively untested.
- `datetime.utcnow` deprecated in 3.12+ (plan-mandated, deferred)

## Conventions

- Python 3.13, no type hints in `config.py` (uses dataclass `field` pattern), Pydantic v2 for schemas
- Tests avoid HTTP calls (unit-test only; mock httpx via pytest-httpx for integration)
- CI/formatting/linting: none configured
