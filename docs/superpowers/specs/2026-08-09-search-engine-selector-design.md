# Spec: Selectable search engine (SearXNG / OpenSERP)

**Date:** 2026-08-09
**Status:** Approved (user reviewed design sections 1-5 + pagination amendment)
**Base:** current `master` (`96079aa`), after remote-LLM providers feature

## Problem

The app searches travel blogs and reviews through a single self-hosted SearXNG instance.
On the target machine the `yandex` engine of SearXNG returns **0 results** (measured
2026-08-09: yandex=0, google=20, ddg=7), so the dominant Russian-language engine —
and the one most relevant for the app's UGC niche — effectively does not participate.

OpenSERP (`karust/openserp`, MIT, self-hosted) exposes a browser-rendered Yandex and a
parallel megasearch (google+yandex+duckduckgo in one call), which is expected to both
restore Yandex coverage and widen the result set.

Goal: let the user choose the search backend **in the interface** per request
(SearXNG / OpenSERP), without removing either service, so the two engines can be
A/B-compared on live data. Optionally fetch more than the first page of results.

## Design decisions (from brainstorming)

| Question | Decision |
|---|---|
| UI granularity | Single select: `SearXNG` / `OpenSERP`; OpenSERP = fixed megasearch (google,yandex,duckduckgo, mode=balanced), no per-engine sub-choice |
| Engine failure handling | No auto-fallback (current behavior): per-query errors are logged and search continues with whatever returned; user re-runs with the other engine manually |
| Record engine in task | Yes: `Task.search_engine` column + shown in `results.html` report header |
| Default engine | `searxng` — backward compatible, current behavior unchanged |
| Pagination | Server-side config, not UI: `SEARCH_MAX_PAGES` (SearXNG pageno loop, default 1) and `OPENSERP_RESULTS_LIMIT` (OpenSERP limit/start loop, default 30) |
| Client architecture | Dispatch in `app/search.py`: `search_urls(object_name, keywords, engine="searxng")` → `_search_searxng` / `_search_openserp`; both return `[{url, title, source_type}]` |
| Deployment | OpenSERP added **alongside** SearXNG in `docker-compose.yml`; app reaches it over the compose network |

## Search layer (`app/search.py`)

- Keep `build_queries`, `classify_source`, `_sort_key` unchanged.
- Rename the current `search_urls` body to `_search_searxng(object_name, keywords)` —
  same logic, plus optional `pageno` loop (see Pagination).
- Add `_search_openserp(object_name, keywords)`:
  - per query from `build_queries`, one megasearch call:
    `GET {openserp_base_url}/search?text=<query>&engines=<openserp_engines>&mode=<openserp_mode>`
    (exact endpoint path and parameter names verified against OpenSERP v2 docs during
    implementation; single-engine endpoint form is `/{engine}/search`).
  - parse envelope `{results: [{url, title, snippet, rank, domain, engine}]}` →
    `{url, title, source_type=classify_source(url, title)}`, dedup by URL (`seen_urls`).
- Public entry stays `search_urls(object_name, keywords, engine="searxng")`:
  - `"searxng"` → `_search_searxng`, `"openserp"` → `_search_openserp`.
- Both branches return exactly `List[Dict]` with keys `url`, `title`, `source_type` —
  downstream (URL cache, classification, LLM analysis, report) is engine-agnostic.

## Config (`app/config.py`)

```python
searxng_base_url: str = field(default_factory=lambda: os.getenv("SEARXNG_BASE_URL", "http://localhost:8888"))
openserp_base_url: str = field(default_factory=lambda: os.getenv("OPENSERP_BASE_URL", "http://localhost:7000"))
openserp_engines: str = field(default_factory=lambda: os.getenv("OPENSERP_ENGINES", "google,yandex,duckduckgo"))
openserp_mode: str = field(default_factory=lambda: os.getenv("OPENSERP_MODE", "balanced"))
search_max_pages: int = field(default_factory=lambda: int(os.getenv("SEARCH_MAX_PAGES", "1")))
openserp_results_limit: int = field(default_factory=lambda: int(os.getenv("OPENSERP_RESULTS_LIMIT", "30")))
```

## Schema (`app/schemas.py`)

- `SearchRequest.search_engine: Literal["searxng", "openserp"] = "searxng"`.
- `ReportData.search_engine: str = "searxng"` (so old reports still render).

## Call chain

- `app/analyzer.py` — `run_analysis(..., llm_settings=None, search_engine="searxng")`,
  passes `search_engine` to `search_urls` (analyzer.py:83).
- `app/main.py` — `api_search` stores `search_engine=body.search_engine` on the `Task`
  and passes it as an extra positional argument to `run_analysis`.
- `app/report.py` — `build_report` copies `task.search_engine` into `ReportData`.

## DB migration (`app/models.py` + `app/database.py`)

- `Task.search_engine = Column(String, nullable=False, default="searxng")`.
- `init_db()` gains `_ensure_tasks_search_engine` following the existing pattern
  (`_ensure_results_source_type`, database.py:21-28): inspect `tasks` columns and run
  `ALTER TABLE tasks ADD COLUMN search_engine VARCHAR(10) DEFAULT 'searxng'` if missing.
- Existing rows get `searxng` — no data loss, no destructive migration.

## Frontend (`app/templates/index.html`)

- Inline labeled select before the submit button (not a details panel — engine choice
  must be visible for A/B):
  - `<select id="search-engine">`: `SearXNG` (`searxng`) / `OpenSERP` (`openserp`).
- Persist in `localStorage` (key `search_engine`); load on page init; mini-version of
  the `llmLoadSettings`/`llmCollectSettings` pattern (single select, no field groups).
- Submit handler adds `search_engine: document.getElementById('search-engine').value`
  to the `POST /api/search` body.
- `results.html`: report header row "Поисковый движок: ..." from `report.search_engine`
  (defaults to `searxng` when absent).

## Pagination (server-side config)

- **SearXNG** (`_search_searxng`): loop `pageno=1..search_max_pages`, adding `pageno` to
  `params`. Overlap between pages/engines is deduped by the existing `seen_urls`.
  Default `SEARCH_MAX_PAGES=1` reproduces current behavior exactly.
- **OpenSERP** (`_search_openserp`): request `limit=<openserp_results_limit>`; if the
  envelope reports `pagination.has_more`, continue from `start=next_start` until the
  target unique-URL count is reached or `has_more=false`; safety cap of ~5 rounds to
  prevent an infinite loop. Default `OPENSERP_RESULTS_LIMIT=30`.

## Deployment (`cultural-history-app/docker-compose.yml`)

- New service **alongside** `searxng` (nothing removed):
  ```yaml
  openserp:
    image: karust/openserp
    container_name: openserp
    ports:
      - "7000:7000"   # public for curl diagnostics, as SearXNG's 8888
    restart: unless-stopped
  ```
- `app` service env additions: `OPENSERP_BASE_URL=http://openserp:7000`,
  `SEARCH_MAX_PAGES=2`, `OPENSERP_RESULTS_LIMIT=50` (explicit defaults).
- `.env.example` documents all new variables.
- Dev machine has no Docker CLI: compose validated via venv PyYAML; real run/verification
  happens on the target machine (deploy checklist).

## Files touched

- Modify: `app/search.py`, `app/config.py`, `app/schemas.py`, `app/analyzer.py`,
  `app/main.py`, `app/models.py`, `app/database.py`, `app/report.py`,
  `app/templates/index.html`, `app/templates/results.html`, `docker-compose.yml`,
  `.env.example`, `AGENTS.md` (architecture note), `tests/test_search.py`
- Create: `tests/test_search_openserp.py` (for-the-record pytest)

## Testing / verification

- pytest files written "for the record" (pytest hangs on this dev machine per AGENTS.md).
- venv throwaway scripts (`C:\Temp\opencode\manual_test_*`): mock `httpx.AsyncClient`;
  assert OpenSERP request shape (`text`, `engines`, `mode`, `limit`, `start`), envelope
  parsing, pagination loop (`has_more`/`next_start`), dedup, and that the dispatcher
  routes `engine` to the right client. Regression check: `_search_searxng` behavior
  unchanged with `search_max_pages=1`.
- e2e via throwaway script on `run_analysis` with `search_engine="openserp"` against a
  mocked OpenSERP.
- Migration check: run `init_db` against a DB schema without `search_engine`; verify the
  column is added and existing rows read as `searxng`.
- Frontend: manual template inspection (`search_engine` in POST body, localStorage,
  results header row).

## Out of scope

- Per-engine sub-choice inside OpenSERP (fixed megasearch per user decision).
- Auto-fallback to the other engine on failure (user decision: no fallback).
- Parallelizing the sequential per-query loop in `search_urls` (separate optimization).
- OpenSERP connection test button (curl is sufficient for diagnostics).
- Using OpenSERP's built-in page-content extraction (`extract` param) — the app has its
  own scraper.
