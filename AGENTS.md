# AGENTS.md

## Overview

Cultural History Analysis App — a FastAPI web service that searches travel blogs and reviews for mentions of cultural/historical objects, analyzes relevance via an LLM (local LM Studio or remote YandexGPT/OpenAI-compatible), and generates reports.

## Repo layout

- `cultural-history-app/` — Python project (FastAPI + SQLAlchemy async + aiosqlite)
  - `app/` — package: `config.py`, `database.py`, `models.py`, `schemas.py`, `llm.py`, `llm_providers.py`, `search.py`, `source_type.py`, `scraper.py`, `analyzer.py`, `report.py`, `main.py`, `templates/`
  - `tests/` — pytest files: `test_llm.py`, `test_llm_providers.py`, `test_search.py`, `test_search_engine.py`, `test_search_openserp.py`, `test_source_type.py`, `test_scraper.py`, `test_api.py`, `test_integration.py`
  - `venv/` — Python 3.13 virtual env (recreated 2026-08-11 on Python 3.13.15)
  - `requirements.txt` — pinned deps; `Dockerfile`, `docker-compose.yml` (3 services); `DEPLOYMENT.md` (target-machine checklist, Russian)
  - `.env` — local dev config (gitignored); `.env.example` documents overrides
  - `data/` — gitignored, SQLite DB created at runtime
- `Тревел блоги.docx` — travel blogs source data (Russian)
- `docs/superpowers/` — specs and plans (spec-driven development artifacts)
- `.superpowers/` — SDD progress ledger per feature wave (self-ignored via its own `.gitignore` with `*`)

## Current state

HEAD: `afd4af7`. Original plan tasks 1–10 are complete; later feature waves landed on top (see `git log` and `.superpowers/sdd/` for detail). An unimplemented design spec for keyword matching + CSV export exists at `docs/superpowers/specs/2026-08-12-keyword-matching-csv-export-design.md`:
- Selectable search backend: SearXNG or OpenSERP (`search_engine`), deployed via compose
- UGC-priority search: query expansion + heuristic source-type sorting + `POST /api/tasks/{id}/stop`
- Remote LLM providers: local (LM Studio) / openai (OpenAI-compatible) / yandex (Yandex Cloud), connection tested via `POST /api/llm/test`

## How to work

- `cd cultural-history-app`
- **Do NOT run `python -m pytest`** — it hangs on this machine (see Known issues). The plan in `docs/superpowers/` says to run pytest; skip those steps. Verify with the venv python directly:
  - Pure functions: `.\venv\Scripts\python.exe -c "from app.scraper import extract_text, text_hash; from app.source_type import classify_source; from app.search import build_queries; print('OK')"`
  - Imports: `.\venv\Scripts\python.exe -c "from app.config import settings; from app.models import Task; from app.schemas import SearchRequest; print('OK')"`
  - Async functions needing mocks (httpx/aiohttp): write a throwaway script that monkeypatches `httpx.AsyncClient` on the module under test and calls the async fn via `asyncio.run()`. E.g. for `app.search._search_searxng`, patch `httpx.AsyncClient.get` to return a canned JSON with a `results` list, then assert on the returned URLs.
- Run app: `uvicorn app.main:app --reload` (needs SearXNG on :8888, OpenSERP on :7000, LM Studio on :1234 per `.env`)
- Docker is installed on the dev machine (29.6.2), so e2e verification can run locally: `docker compose up -d --build`, then browse `http://localhost:8000`

## Deployment

- Docker mode: `cd cultural-history-app; docker compose up -d --build` — three services: app at :8000, SearXNG at :8888, OpenSERP at :7000
- App container reaches LM Studio on the host via `host.docker.internal:1234`, SearXNG via `http://searxng:8080`, OpenSERP via `http://openserp:7000` (compose network)
- SQLite persists via `./data:/app/data` volume
- Host mode: `docker compose up -d searxng openserp` + `uvicorn app.main:app --reload` (config.py defaults point to localhost)
- No `.env` needed in either mode; `.env.example` documents overrides; do not commit `.env`
- Full deployment instructions for the target machine: `cultural-history-app/DEPLOYMENT.md`

## Architecture notes

- Async throughout: `httpx.AsyncClient` for LLM and search engines, `aiohttp` for page fetching
- SQLAlchemy async with `aiosqlite` driver
- LLM providers in `app/llm_providers.py`: `LLMProvider` ABC + `get_provider(LLMSettings)` factory. `local` hits `{endpoint}/v1/chat/completions` (OpenAI-compatible, default LM Studio), `openai` adds a Bearer key, `yandex` uses `gpt://{folder_id}/{model}/{version}` at `https://llm.api.cloud.yandex.net/foundationModels/v1/completion`. All: temperature=0.1, max_tokens=256. Default model `meta-llama-3.1-8b-instruct` (configurable)
- Connection settings for remote providers live in browser `localStorage` and are sent per-request as `LLMSettings`; `POST /api/llm/test` validates a connection
- Prompt engineering (`app/llm.py`): strict JSON-only responses; `_parse_response()` extracts JSON (tolerates fenced blocks); `_coerce_result()` forces booleans/float, whitelists `source_type` to `blog/forum/social/official/agency/other`; `analyze_text_with_retry()` falls back to a zeroed result after retries
- DB schema: `tasks`, `results`, `url_cache`; `tasks.search_engine` column exists with a migration guard in `database.py` (`_ensure_column` pattern — reuse it for any future column)
- Search (`app/search.py`): `build_queries()` = `{object_name}`, `{object_name} {keyword}`, plus UGC markers (`отзывы, блог, форум, впечатления`); engine dispatch via `search_urls(object_name, keywords, engine=...)`. SearXNG paginates `SEARCH_MAX_PAGES` pages; OpenSERP hits `/mega/search` with `OPENSERP_RESULTS_LIMIT` and `has_more` pagination rounds. Results are deduped by URL and sorted by heuristic `source_type` (UGC first) from `app/source_type.py` `classify_source()`. LLM returns the authoritative `source_type`
- Search backend is selectable per request via `SearchRequest.search_engine` (`"searxng" | "openserp"`), stored on the task, shown in the report header
- Keyword matching is local and deterministic (`app/keyword_match.py`): `snowballstemmer` stems page + keyword tokens, matches by contiguous subsequence. Multi-keyword logic is OR (at least one match)
- Stop endpoint `POST /api/tasks/{id}/stop` marks task `stopped`

## Version pinning

`requirements.txt` has specific bounds to avoid dependency conflicts:
- `httpx<0.28` required by `pytest-httpx<0.36`
- `pytest<9` required by `pytest-httpx<0.36`

## Known issues

- **pytest hangs on Windows/Python 3.13** — any `python -m pytest` invocation stalls at startup (during collection, with pytest-asyncio + pytest-httpx installed), even for pure-sync test files. Run test logic via `python -c` scripts or throwaway monkeypatch scripts instead.
- **aiohttp import stall (intermittent)** — aiohttp 3.14.3 was observed to hang on import on Python 3.13 Windows, but imports fine on fresh runs (as of this writing). `tests/test_scraper.py` deliberately imports only the pure functions (`extract_text`, `text_hash`) to stay safe; the async functions (`fetch_page_text`, `fetch_and_analyze`) remain effectively untested.
- `datetime.utcnow` deprecated in 3.12+ (plan-mandated, deferred; still used in `models.py` and `analyzer.py`)

## Conventions

- Python 3.13, no type hints in `config.py` (uses dataclass `field` pattern), Pydantic v2 for schemas
- Tests avoid HTTP calls (unit-test only; mock httpx for integration)
- CI/formatting/linting: none configured
