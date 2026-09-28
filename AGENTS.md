# AGENTS.md

## Overview

Cultural History Analysis App — a FastAPI web service that searches travel blogs and reviews for mentions of cultural/historical objects, analyzes relevance via an LLM (local LM Studio or remote YandexGPT/OpenAI-compatible), and generates reports.

## Repo layout

- `cultural-history-app/` — Python project (FastAPI + SQLAlchemy async + aiosqlite)
  - `app/` — package: `config.py`, `database.py`, `models.py`, `schemas.py`, `llm.py`, `llm_providers.py`, `search.py`, `source_type.py`, `scraper.py`, `analyzer.py`, `report.py`, `main.py`, `templates/`
  - `tests/` — pytest files: `test_llm.py`, `test_llm_providers.py`, `test_search.py`, `test_search_engine.py`, `test_search_openserp.py`, `test_source_type.py`, `test_scraper.py`, `test_keyword_match.py`, `test_api.py`, `test_integration.py`, `test_report.py`, `test_analyzer.py`; `conftest.py` points `DATABASE_URL` at a temp SQLite file *before* importing `app.config` (so tests never touch `./data/app.db`), zeroes the inter-query search delay, snapshots `search_max_pages` / `fetch_concurrency`, and resets the analysis semaphore between tests
  - `pytest.ini` — `asyncio_mode = strict`, function-scoped fixture loops
  - `venv/` — gitignored; the checked-out one is a Windows venv (`venv/Scripts/`), useless on Linux — create a fresh one (`python3 -m venv venv && venv/bin/pip install -r requirements.txt`)
  - `requirements.txt` — pinned deps; `Dockerfile`, `docker-compose.yml` (3 services); `DEPLOYMENT.md` (target-machine checklist, Russian)
  - `scripts/` — `start.sh`/`stop.sh` (Linux/macOS), `start.ps1`/`stop.ps1` + `start.cmd`/`stop.cmd` wrappers (Windows). Docker mode by default, `--host`/`-HostMode` runs uvicorn from a venv. Health probes: app `/`, SearXNG `/`, OpenSERP `/health` (its `/` is 404). `stop` kills only the current user's `uvicorn app.main:app … --port 8000` — other projects on this machine run uvicorn with the same module name on other ports. Verified 2026-09-28: Docker-mode start/stop on Linux works end to end; PowerShell scripts not yet run on a Windows machine
  - `.env` — local dev config (gitignored); `.env.example` documents overrides
  - `data/` — gitignored, SQLite DB created at runtime
- `Тревел блоги.docx` — travel blogs source data (Russian); not yet used by code
- `docs/superpowers/` — specs and plans (spec-driven development artifacts)
- `.superpowers/` — SDD progress ledger per feature wave (self-ignored via its own `.gitignore` with `*`)
- Root `.gitignore` excludes `*.ipynb` / `.ipynb_checkpoints/` — `remotemodeltest.ipynb` contains a live Yandex Cloud API key and must never be committed. `.gitattributes` forces LF line endings.

## Current state

All planned feature waves have landed (see `git log` and `.superpowers/sdd/` for detail):
- Selectable search backend: SearXNG or OpenSERP (`search_engine`), deployed via compose. Default is `openserp` (env `DEFAULT_SEARCH_ENGINE`, read in `config.py`, used as `SearchRequest` default and preselected in the UI). SearXNG returning 0 results falls back to OpenSERP
- UGC-priority search: query expansion + heuristic source-type sorting + `POST /api/tasks/{id}/stop`; inter-query delay `SEARCH_DELAY` to avoid engine bans
- Remote LLM providers: local (LM Studio) / openai (OpenAI-compatible) / yandex (Yandex Cloud, now via its OpenAI-compatible endpoint `https://ai.api.cloud.yandex.net/v1`), connection tested via `POST /api/llm/test`
- Morphology-aware keyword matching (`app/keyword_match.py`) + CSV export (`GET /results/{id}/csv`)

Improvement plan (search quality) is tracked in chat history; stages 0–3 have landed. Next is stage 4: travel-blog domain bias, source mix before start, SearXNG `secret_key`.

## How to work

- `cd cultural-history-app`
- **Tests run normally on Linux**: `venv/bin/python -m pytest -q` — 101 tests, ~2 s. The old "pytest hangs" note applies to the Windows dev machine only (see Known issues). `tests/conftest.py` sets `DATABASE_URL` to a temp SQLite file before `app` is imported
- Search tests use `pytest-httpx` with `add_callback(..., is_reusable=True)` (required since pytest-httpx 0.32; `requirements.txt` pins `>=0.32`). SearXNG and OpenSERP are both on `localhost` in tests — distinguish them by port, not host
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

- Async throughout: `httpx.AsyncClient` for LLM, search engines, and page fetching (shared client per analysis via `make_http_client()`; `SCRAPER_VERIFY_SSL` default false)
- One analysis at a time in-process (`asyncio.Semaphore(1)`); a second request is stored as `queued` until the slot is free. Within an analysis, URL fetches run concurrently up to `FETCH_CONCURRENCY` (default 3) under a write lock so SQLite sessions are not shared. Page text sent to the LLM is truncated to `LLM_TEXT_LIMIT` (default 3000)
- SQLAlchemy async with `aiosqlite` driver
- LLM providers in `app/llm_providers.py`: `LLMProvider` ABC + `get_provider(LLMSettings)` factory. All three speak OpenAI `chat/completions` (`_chat_completions_url` appends `/v1/chat/completions` unless the endpoint already ends in `/v1`). `local` = LM Studio, no auth; `openai` adds `Bearer` key; `yandex` adds `Api-Key`, model id `gpt://{folder_id}/{model}/{version}`, default model `qwen3-235b-a22b-fp8`. temperature=0.1; max_tokens 512 (local/openai) / 1024 (yandex). `_extract_content` falls back to `reasoning_content` when `content` is empty. Default local model `meta-llama-3.1-8b-instruct` (configurable)
- Connection settings for remote providers live in browser `localStorage` and are sent per-request as `LLMSettings`; `POST /api/llm/test` validates a connection
- Prompt engineering (`app/llm.py`): strict JSON-only responses; `_parse_response()` extracts JSON (tolerates fenced blocks); `_coerce_result()` forces booleans/float, whitelists `source_type` to `blog/forum/social/official/agency/other`; `analyze_text_with_retry()` sets `analysis_status=llm_failed` after retries instead of a fake "not mentioned" success
- DB schema: `tasks`, `results`, `url_cache`; extra columns are added with `_ensure_column` in `database.py` (`source_type`, `search_engine`, `search_engine_used`, `error_message`, `analysis_status`, `progress_json`, `stop_requested`). `Result.analysis_status` is `ok` / `fetch_failed` / `llm_failed`. Cache key suffix `#kwv3` — fetch/LLM failures are not written to `url_cache`. Progress while a task runs is also stored on `tasks.progress_json`; `_progress_store` is a process-local cache dropped when the task finishes. On startup, `fail_interrupted_tasks()` marks leftover `pending`/`processing`/`queued` rows `failed` ("прервано перезапуском"). `GET /api/tasks/{id}` returns JSON status from memory or DB. SSE treats `queued` as in-progress.
- Search (`app/search.py`): `build_queries()` = `{object_name}`, `{object_name} {keyword}`, plus UGC markers (`отзывы, блог, форум, впечатления`); engine dispatch via `search_urls` / `search_urls_detailed` (the latter also returns the engine that actually ran and whether SearXNG fell back to OpenSERP). Both engines paginate up to `SEARCH_MAX_PAGES` (default 3) and sleep `SEARCH_DELAY` seconds between queries; OpenSERP hits `/mega/search` with `OPENSERP_RESULTS_LIMIT` and stops early when `pagination.has_more` is false. `engine="searxng"` falls back to OpenSERP when SearXNG yields nothing. Results are deduped by URL and sorted by heuristic `source_type` (UGC first) from `app/source_type.py` `classify_source()` — that heuristic scale (`ugc/unknown/official/agency`) is only for ordering; the report shows the LLM's `source_type` (`blog/forum/social/official/agency/other`)
- Search backend is selectable per request via `SearchRequest.search_engine` (`"searxng" | "openserp"`), defaulting to `settings.default_search_engine`, stored on the task, shown in the report header
- Keyword matching is local and deterministic (`app/keyword_match.py`): `snowballstemmer` stems page + keyword tokens, matches by contiguous subsequence. `match_keywords()` returns `(matched_keywords, matched_word_forms)`; the report shows the word forms found in the text. Stem comparison is prefix-based: keyword stem may be a prefix of the page stem (`визант` → `византийск`); the reverse only when the page stem is ≥4 chars (so `в`/`виз` never match `Византия`). Multi-keyword logic is OR (at least one match)
- Stop endpoint `POST /api/tasks/{id}/stop` marks task `stopped`

## Version pinning

`requirements.txt` has specific bounds to avoid dependency conflicts:
- `httpx<0.28` required by `pytest-httpx<0.36`
- `pytest<9` required by `pytest-httpx<0.36`

## Known issues

- **pytest hangs on Windows/Python 3.13 only** — on the Windows dev machine `python -m pytest` stalled during collection. On Linux (Python 3.12, verified 2026-09-28) the full suite runs in ~2 s. `aiohttp` is no longer a dependency (`scraper.py` uses httpx). Remaining suspects: the auto-registered `anyio` pytest plugin, OneDrive/Cyrillic path locking `.pytest_cache`, Python 3.13 itself. `pytest.ini` already sets `-p no:anyio` and `faulthandler_timeout = 60` (a stalled run dumps all thread stacks after 60 s — read that first). To diagnose on Windows: `pytest --co -q -o faulthandler_timeout=20`, `pytest --co -p no:asyncio -p no:httpx`, then retry from a plain `C:\dev\...` path. Workaround: run tests in the Linux app image (`docker run --rm -v "${PWD}:/app" -w /app cultural-history-app-app python -m pytest -q`, see README) or fall back to `python -c` scripts.
- `scraper.fetch_page_text` passes raw bytes to BeautifulSoup so meta/HTTP charset (including cp1251) is honoured; empty bodies still short-circuit before lxml
- `report.build_report`: `total_mentions` = ok rows with `mentions_object=True`; failed fetches/LLM calls are counted separately and excluded from keyword percentages. Empty search with no manual URLs marks the task `failed` with `error_message`. SearXNG→OpenSERP fallback is shown as `searxng → openserp` in the report header.
- `datetime.now(timezone.utc)` via `app.models.utcnow` (replaces deprecated `datetime.utcnow`)

## Conventions

- Python 3.12+ (3.13 on the original Windows machine), no type hints in `config.py` (uses dataclass `field` pattern), Pydantic v2 for schemas
- Tests avoid HTTP calls (unit-test only; mock httpx for integration)
- CI/formatting/linting: none configured
