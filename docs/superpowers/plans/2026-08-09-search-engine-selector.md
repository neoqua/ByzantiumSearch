# Selectable Search Engine (SearXNG / OpenSERP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick SearXNG or OpenSERP (megasearch: google+yandex+duckduckgo) as the search backend per request, record the choice on the task, and optionally fetch more than the first page of results.

**Architecture:** A dispatcher in `app/search.py` routes to `_search_searxng` (current logic + `pageno` loop) or `_search_openserp` (megasearch + `limit`/`start` pagination); both return `[{url, title, source_type}]`. `SearchRequest.search_engine` threads through `main.py` → `run_analysis` → `search_urls`, is persisted on `Task`, and surfaces in the report header. OpenSERP is added to `docker-compose.yml` alongside SearXNG.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async + aiosqlite, httpx, Jinja2, Docker Compose, OpenSERP (self-hosted, port 7000).

## Global Constraints

- **NEVER run `python -m pytest`** — it hangs on this dev machine. All pytest files are written "for the record" only. Verification uses the venv interpreter directly with throwaway scripts in `C:\Temp\opencode`.
- Venv interpreter: `F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app\venv\Scripts\python.exe`; run venv commands with workdir `F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app`.
- Throwaway scripts must NOT import `aiohttp` directly (import can stall). Importing `httpx` is safe.
- Throwaway scripts run from `C:\Temp\opencode` must insert the app dir on `sys.path` first: `sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")`.
- `app/config.py` uses the dataclass `field`/`os.getenv` pattern — **no type hints**, new settings follow it exactly.
- Pydantic v2 models never equal plain dicts — assert with `model_dump()` where needed.
- SQLite migration pattern: `ALTER TABLE ... ADD COLUMN` guarded by `inspect` (see `app/database.py:_ensure_results_source_type`).
- Commit style: short messages `feat:`, `fix:`, `docs:`; commit only the task's files. Never commit `.env`, `.superpowers/`, `test_tmp.py`, or throwaway scripts in `C:\Temp\opencode`.
- `.env.example` documents overrides; `.env` is never committed.
- No Docker CLI on the dev machine — `docker-compose.yml` is validated with the venv's PyYAML, never by running docker.
- OpenSERP megasearch response is the v2 envelope: `{results: [{url, title, snippet, rank, domain, engine}], pagination: {page, has_more, next_start}}`. CONFIRMED during Task 2 (2026-08-09, karust/openserp README): megasearch endpoint is `GET {base}/mega/search` with `text`, `engines`, `mode` (`balanced`|`fast`|`any`), `limit` (max 100), `start` (offset 0/10/20); available engines `google,yandex,baidu,bing,duckduckgo,ecosia`; megasearch dedups by normalized URL and returns `clusters`.

---

### Task 1: Config + schema + Task column + DB migration

**Files:**
- Modify: `app/config.py:24` (after `lm_studio_model`), `app/schemas.py:14-19` (SearchRequest) and `:45-54` (ReportData), `app/models.py:15-27` (Task), `app/database.py:14-18` (init_db) + `:28` (new helper)
- Test: `tests/test_search_engine.py` (create, for-the-record)
- Throwaway: `C:\Temp\opencode\manual_test_migration.py` (create)

**Interfaces:**
- Produces: `settings.openserp_base_url: str`, `settings.openserp_engines: str`, `settings.openserp_mode: str`, `settings.search_max_pages: int`, `settings.openserp_results_limit: int`; `SearchRequest.search_engine: Literal["searxng","openserp"] = "searxng"`; `ReportData.search_engine: str = "searxng"`; `Task.search_engine: Column(String, default="searxng")`; `init_db()` adds the `search_engine` column to an existing `tasks` table.

- [ ] **Step 1: Write the for-the-record test** — create `tests/test_search_engine.py`:

```python
from app.config import settings
from app.schemas import SearchRequest, ReportData


def test_search_request_defaults_to_searxng():
    r = SearchRequest(object_name="X", keywords="k")
    assert r.search_engine == "searxng"


def test_search_request_accepts_openserp():
    r = SearchRequest(object_name="X", keywords="k", search_engine="openserp")
    assert r.search_engine == "openserp"


def test_report_data_has_search_engine_default():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[],
    )
    assert r.search_engine == "searxng"


def test_config_openserp_defaults():
    assert settings.openserp_base_url == "http://localhost:7000"
    assert settings.openserp_engines == "google,yandex,duckduckgo"
    assert settings.openserp_mode == "balanced"
    assert settings.search_max_pages == 1
    assert settings.openserp_results_limit == 30
```

Do not run it (pytest hangs). It documents the contract.

- [ ] **Step 2: Add config fields** — `app/config.py`, after the `lm_studio_model` field:

```python
    openserp_base_url: str = field(
        default_factory=lambda: os.getenv("OPENSERP_BASE_URL", "http://localhost:7000")
    )
    openserp_engines: str = field(
        default_factory=lambda: os.getenv("OPENSERP_ENGINES", "google,yandex,duckduckgo")
    )
    openserp_mode: str = field(
        default_factory=lambda: os.getenv("OPENSERP_MODE", "balanced")
    )
    search_max_pages: int = field(
        default_factory=lambda: int(os.getenv("SEARCH_MAX_PAGES", "1"))
    )
    openserp_results_limit: int = field(
        default_factory=lambda: int(os.getenv("OPENSERP_RESULTS_LIMIT", "30"))
    )
```

- [ ] **Step 3: Add schema fields** — `app/schemas.py`:

SearchRequest (after `llm_settings`):

```python
    search_engine: Literal["searxng", "openserp"] = "searxng"
```

ReportData (after `results`):

```python
    search_engine: str = "searxng"
```

- [ ] **Step 4: Add Task column** — `app/models.py`, in `Task` after `manual_urls`:

```python
    search_engine = Column(String, nullable=False, default="searxng")
```

- [ ] **Step 5: Add migration (shared column helper)** — `app/database.py`:

Keep migrations DRY: extract a generic guarded-ALTER helper and delegate both columns to it. Add the shared helper:

```python
def _ensure_column(sync_conn, table, column, ddl):
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        sync_conn.execute(text(ddl))
```

In `init_db`, after the `_ensure_results_source_type` line:

```python
        await conn.run_sync(_ensure_tasks_search_engine)
```

Refactor `_ensure_results_source_type` into a delegate (preserve the existing DDL string):

```python
def _ensure_results_source_type(sync_conn):
    _ensure_column(sync_conn, "results", "source_type",
                   "ALTER TABLE results ADD COLUMN source_type VARCHAR(20)")
```

Add `_ensure_tasks_search_engine` as a delegate:

```python
def _ensure_tasks_search_engine(sync_conn):
    _ensure_column(sync_conn, "tasks", "search_engine",
                   "ALTER TABLE tasks ADD COLUMN search_engine VARCHAR(10) DEFAULT 'searxng'")
```

- [ ] **Step 6: Verify migration with throwaway script** — create `C:\Temp\opencode\manual_test_migration.py`:

```python
import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

db = Path(r"C:\Temp\opencode\migration_test.db")
if db.exists():
    db.unlink()

conn = sqlite3.connect(str(db))
conn.execute("CREATE TABLE tasks (id VARCHAR PRIMARY KEY, object_name VARCHAR NOT NULL, "
             "keywords VARCHAR NOT NULL, annual_visitors INTEGER, manual_urls TEXT, "
             "status VARCHAR, created_at DATETIME, completed_at DATETIME)")
conn.execute("INSERT INTO tasks (id, object_name, keywords, status) VALUES ('t1', 'OldObj', 'kw', 'completed')")
conn.commit()
conn.close()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
import asyncio
from app.database import init_db
asyncio.run(init_db())

conn = sqlite3.connect(str(db))
cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
assert "search_engine" in cols, f"column missing: {cols}"
row = conn.execute("SELECT search_engine FROM tasks WHERE id='t1'").fetchone()
assert row is not None and row[0] == "searxng", row
print("MIGRATION: PASS")
```

Run it:

```
cd cultural-history-app
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_migration.py
```

Expected: `MIGRATION: PASS`

- [ ] **Step 7: Import sanity check**

```
.\venv\Scripts\python.exe -c "from app.config import settings; from app.schemas import SearchRequest, ReportData; from app.models import Task; from app.database import init_db; print('IMPORT_OK'); print(settings.openserp_base_url, settings.search_max_pages)"
```

Expected: `IMPORT_OK http://localhost:7000 1`

- [ ] **Step 8: Commit**

```bash
git add cultural-history-app/app/config.py cultural-history-app/app/schemas.py cultural-history-app/app/models.py cultural-history-app/app/database.py cultural-history-app/tests/test_search_engine.py
git commit -m "feat: search engine config, schema field and task column"
```

---

### Task 2: search.py dispatcher + OpenSERP client + pagination

**Files:**
- Modify: `app/search.py` (full rewrite of the function bodies, keep `build_queries` and imports), `tests/test_search.py` (append dispatcher test)
- Test: `tests/test_search_openserp.py` (create, for-the-record)
- Throwaway: `C:\Temp\opencode\manual_test_search_engine.py` (create)

**Interfaces:**
- Consumes: `settings.searxng_base_url`, `settings.openserp_base_url`, `settings.openserp_engines`, `settings.openserp_mode`, `settings.search_max_pages`, `settings.openserp_results_limit` (from Task 1).
- Produces: `async search_urls(object_name: str, keywords: List[str], engine: str = "searxng") -> List[Dict[str, str]]` — dispatches to `_search_searxng` / `_search_openserp`, returns `[{url, title, source_type}]` sorted by `source_type` priority.

- [ ] **Step 1: Write the for-the-record OpenSERP tests** — create `tests/test_search_openserp.py`:

```python
import pytest
import httpx
from app.search import search_urls
from app.source_type import UGC_QUERY_MARKERS


@pytest.mark.asyncio
async def test_openserp_request_shape(httpx_mock):
    captured = {}

    def respond(request):
        captured.setdefault("params", dict(request.url.params))
        return httpx.Response(200, json={
            "results": [
                {"url": "https://blog.ru/post1", "title": "Отзыв", "rank": 1, "domain": "blog.ru"},
            ],
            "pagination": {"page": 1, "has_more": False, "next_start": 30},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("TestObject", ["kw1"], engine="openserp")
    assert captured["params"]["text"] == "TestObject"
    assert captured["params"]["engines"] == "google,yandex,duckduckgo"
    assert captured["params"]["mode"] == "balanced"
    assert captured["params"]["limit"] == "30"
    assert captured["params"]["start"] == "0"
    assert results[0]["url"] == "https://blog.ru/post1"
    assert results[0]["source_type"] == "ugc"


@pytest.mark.asyncio
async def test_openserp_paginates(httpx_mock):
    calls = []

    def respond(request):
        start = request.url.params["start"]
        calls.append(start)
        if start == "0":
            return httpx.Response(200, json={
                "results": [{"url": f"https://a/{i}", "title": "t"} for i in range(2)],
                "pagination": {"page": 1, "has_more": True, "next_start": 30},
            })
        return httpx.Response(200, json={
            "results": [{"url": f"https://b/{i}", "title": "t"} for i in range(2)],
            "pagination": {"page": 2, "has_more": False, "next_start": 60},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    n_queries = 1 + len(UGC_QUERY_MARKERS)  # object name + one query per UGC marker
    assert len(calls) == 2 * n_queries
    assert calls == ["0", "30"] * n_queries
    assert len(results) == 4


@pytest.mark.asyncio
async def test_openserp_dedups_across_pages(httpx_mock):
    def respond(request):
        if request.url.params["start"] == "0":
            return httpx.Response(200, json={
                "results": [{"url": "https://a/dup", "title": "t"}],
                "pagination": {"has_more": True, "next_start": 30},
            })
        return httpx.Response(200, json={
            "results": [{"url": "https://a/dup", "title": "t"}],
            "pagination": {"has_more": False, "next_start": 60},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_openserp_limit_cap_stops_at_five_rounds(httpx_mock):
    def respond(request):
        return httpx.Response(200, json={
            "results": [{"url": "https://a/dup", "title": "t"}],
            "pagination": {"has_more": True, "next_start": 30},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    assert len(results) == 1  # 5 rounds, all deduped, loop capped
```

- [ ] **Step 2: Append dispatcher test** — `tests/test_search.py`:

```python
@pytest.mark.asyncio
async def test_search_urls_defaults_to_searxng(httpx_mock):
    def respond(request):
        assert request.url.params["pageno"] == "1"
        return httpx.Response(200, json={"results": [
            {"url": "https://example.com/x", "title": "X"},
        ]})

    httpx_mock.add_callback(respond)
    results = await search_urls("Test", ["k"])
    assert results[0]["url"] == "https://example.com/x"
```

- [ ] **Step 3: Rewrite `app/search.py`** — full new content (imports and `build_queries`/`_sort_key` unchanged, bodies rewritten):

```python
import logging
from typing import List, Dict
import httpx
from app.config import settings
from app.source_type import classify_source, SOURCE_PRIORITY, UGC_QUERY_MARKERS

logger = logging.getLogger(__name__)


def build_queries(object_name: str, keywords: List[str]) -> List[str]:
    queries = [object_name]
    for kw in keywords:
        queries.append(f"{object_name} {kw}")
    for marker in UGC_QUERY_MARKERS:
        queries.append(f"{object_name} {marker}")
    return queries


def _sort_key(item: Dict[str, str]) -> int:
    return SOURCE_PRIORITY.get(item.get("source_type", "unknown"), 1)


def _extract(item: Dict) -> Dict[str, str]:
    url = item.get("url", "").strip()
    return {
        "url": url,
        "title": item.get("title", ""),
        "source_type": classify_source(url, item.get("title", "")),
    }


async def _search_searxng(object_name: str, keywords: List[str]) -> List[Dict[str, str]]:
    queries = build_queries(object_name, keywords)
    seen_urls: set = set()
    results: List[Dict[str, str]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                for page in range(1, settings.search_max_pages + 1):
                    params = {
                        "q": query,
                        "format": "json",
                        "language": "ru-RU",
                        "categories": "general",
                        "pageno": page,
                    }
                    resp = await client.get(
                        f"{settings.searxng_base_url}/search", params=params
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for item in data.get("results", []):
                        url = item.get("url", "").strip()
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(_extract(item))
            except Exception as e:
                logger.warning("Search query '%s' failed: %s", query, e)
    return results


async def _search_openserp(object_name: str, keywords: List[str]) -> List[Dict[str, str]]:
    queries = build_queries(object_name, keywords)
    seen_urls: set = set()
    results: List[Dict[str, str]] = []
    engines = settings.openserp_engines
    mode = settings.openserp_mode
    limit = settings.openserp_results_limit

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                start = 0
                for _round in range(5):
                    params = {
                        "text": query,
                        "engines": engines,
                        "mode": mode,
                        "limit": limit,
                        "start": start,
                    }
                    resp = await client.get(
                        f"{settings.openserp_base_url}/mega/search", params=params
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for item in data.get("results", []):
                        url = item.get("url", "").strip()
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(_extract(item))
                    pagination = data.get("pagination") or {}
                    if not pagination.get("has_more"):
                        break
                    start = pagination.get("next_start", start + limit)
            except Exception as e:
                logger.warning("OpenSERP query '%s' failed: %s", query, e)
    return results


async def search_urls(
    object_name: str, keywords: List[str], engine: str = "searxng"
) -> List[Dict[str, str]]:
    if engine == "openserp":
        results = await _search_openserp(object_name, keywords)
    else:
        results = await _search_searxng(object_name, keywords)
    results.sort(key=_sort_key)
    return results
```

- [ ] **Step 4: Verify both clients with throwaway script** — create `C:\Temp\opencode\manual_test_search_engine.py`:

```python
import sys
import asyncio

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")
import httpx
from app.search import search_urls


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


calls = []

async def fake_get(self, url, params=None):
    calls.append((url, dict(params)))
    if "localhost:7000" in url:
        return _Resp({"results": [
            {"url": "https://blog.ru/p1", "title": "Отзыв"},
            {"url": "https://blog.ru/p2", "title": "Блог"},
        ], "pagination": {"has_more": False, "next_start": 30}})
    return _Resp({"results": [
        {"url": "https://example.com/s1", "title": "T"},
    ]})

orig = httpx.AsyncClient.get
httpx.AsyncClient.get = fake_get
try:
    r1 = asyncio.run(search_urls("Объект", [], engine="searxng"))
    assert r1 and r1[0]["url"] == "https://example.com/s1", r1
    r2 = asyncio.run(search_urls("Объект", [], engine="openserp"))
    assert any(u["url"] == "https://blog.ru/p1" for u in r2), r2
    assert any(u["source_type"] == "ugc" for u in r2), r2
finally:
    httpx.AsyncClient.get = orig
print("SEARCH_ENGINE_DISPATCH: PASS")

page_calls = []

async def fake_get_page(self, url, params=None):
    page_calls.append(dict(params))
    start = params.get("start", 0)
    if start == 0:
        return _Resp({"results": [{"url": f"https://x/{i}", "title": "t"} for i in range(3)],
                      "pagination": {"has_more": True, "next_start": 30}})
    return _Resp({"results": [{"url": f"https://y/{i}", "title": "t"} for i in range(3)],
                  "pagination": {"has_more": False, "next_start": 60}})

httpx.AsyncClient.get = fake_get_page
try:
    r3 = asyncio.run(search_urls("Объект", [], engine="openserp"))
    assert len(page_calls) == 10, page_calls
    assert r3[0]["url"].startswith("https://x/"), r3
finally:
    httpx.AsyncClient.get = orig
print("OPENSERP_PAGINATION: PASS")
```

Run it:

```
cd cultural-history-app
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_search_engine.py
```

Expected: `SEARCH_ENGINE_DISPATCH: PASS` and `OPENSERP_PAGINATION: PASS`

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/search.py cultural-history-app/tests/test_search.py cultural-history-app/tests/test_search_openserp.py
git commit -m "feat: OpenSERP megasearch client and engine dispatcher"
```

---

### Task 3: Thread search_engine through the call chain

**Files:**
- Modify: `app/analyzer.py:53-59` (signature) and `:83` (call), `app/main.py:47-53` (Task) and `:66-73` (add_task), `app/report.py:40-51` (ReportData)
- Test: `tests/test_api.py` (append) and fix `_Task` stub at `:78-84`

**Interfaces:**
- Consumes: `SearchRequest.search_engine` (Task 1), `search_urls(..., engine=...)` (Task 2).
- Produces: `run_analysis(task_id, object_name, keywords_raw, manual_urls_raw=None, llm_settings=None, search_engine="searxng")`; `Task.search_engine` persisted; `ReportData.search_engine` populated from the task.

- [ ] **Step 1: Append for-the-record API tests** — `tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_api_search_persists_search_engine(api_client):
    resp = await api_client.post("/api/search", json={
        "object_name": "Obj", "keywords": "kw", "search_engine": "openserp",
    })
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    from app.database import async_session
    from app.models import Task
    async with async_session() as s:
        task = await s.get(Task, task_id)
        assert task.search_engine == "openserp"


@pytest.mark.asyncio
async def test_api_search_forwards_search_engine(api_client):
    calls = []
    orig = main_module.run_analysis

    async def capture(*args, **kwargs):
        calls.append((args, kwargs))

    main_module.run_analysis = capture
    try:
        resp = await api_client.post("/api/search", json={
            "object_name": "Obj", "keywords": "kw", "search_engine": "openserp",
        })
    finally:
        main_module.run_analysis = orig
    assert resp.status_code == 200
    assert calls and calls[0][0][5] == "openserp"  # 6th positional arg (search_engine) to add_task


def test_report_data_carries_search_engine():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[], search_engine="openserp",
    )
    assert r.search_engine == "openserp"
```

Also update the existing `_Task` stub in `test_report_build_passes_source_type` (currently lines 78-84) to include `search_engine = "searxng"` so `build_report` can read it.

- [ ] **Step 2: Update `app/analyzer.py`** — signature:

```python
async def run_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str] = None,
    llm_settings: Optional[LLMSettings] = None,
    search_engine: str = "searxng",
):
```

and the search call at analyzer.py:83:

```python
            search_results = await search_urls(object_name, keywords, engine=search_engine)
```

- [ ] **Step 3: Update `app/main.py`** — in `api_search`:

```python
    task = Task(
        object_name=body.object_name,
        keywords=body.keywords,
        annual_visitors=body.annual_visitors,
        manual_urls=body.manual_urls,
        search_engine=body.search_engine,
        status="pending",
    )
```

and the background call:

```python
    background_tasks.add_task(
        run_analysis,
        task.id,
        body.object_name,
        body.keywords,
        body.manual_urls,
        body.llm_settings,
        body.search_engine,
    )
```

- [ ] **Step 4: Update `app/report.py`** — add to the `ReportData(...)` constructor:

```python
        search_engine=task.search_engine,
```

- [ ] **Step 5: Import + threading check via throwaway script** — create `C:\Temp\opencode\manual_test_threading.py`:

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

db = Path(r"C:\Temp\opencode\threading_test.db")
if db.exists():
    db.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"

import asyncio
from app.database import init_db, async_session
from app.models import Task
from app import analyzer as analyzer_mod
from app import main as main_mod

asyncio.run(init_db())

async def seed_task():
    async with async_session() as s:
        s.add(Task(id="t1", object_name="Obj", keywords="kw", search_engine="openserp"))
        await s.commit()

asyncio.run(seed_task())

seen = {}

async def fake_search_urls(object_name, keywords, engine="searxng"):
    seen["engine"] = engine
    return [{"url": "https://blog.ru/x", "title": "X", "source_type": "ugc"}]

async def fake_fetch_and_analyze(*args, **kwargs):
    return {"mentions_object": True, "has_keyword": True, "source_type": "blog",
            "relevance_score": 0.9}

orig_search = analyzer_mod.search_urls
orig_fetch = analyzer_mod.fetch_and_analyze
analyzer_mod.search_urls = fake_search_urls
analyzer_mod.fetch_and_analyze = fake_fetch_and_analyze
try:
    asyncio.run(analyzer_mod.run_analysis("t1", "Obj", "kw", None, None, "openserp"))
finally:
    analyzer_mod.search_urls = orig_search
    analyzer_mod.fetch_and_analyze = orig_fetch

assert seen.get("engine") == "openserp", seen

from app.database import async_session
from app.models import Task, Result

async def check():
    async with async_session() as s:
        task = await s.get(Task, "t1")
        assert task.search_engine == "openserp", task.search_engine
        rows = (await s.execute(__import__("sqlalchemy").select(Result).where(Result.task_id == "t1"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].mentions_object is True

asyncio.run(check())

print("THREADING: PASS")
```

Run it:

```
cd cultural-history-app
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_threading.py
```

Expected: `THREADING: PASS`

- [ ] **Step 6: Commit**

```bash
git add cultural-history-app/app/analyzer.py cultural-history-app/app/main.py cultural-history-app/app/report.py cultural-history-app/tests/test_api.py
git commit -m "feat: thread search_engine through analysis chain"
```

---

### Task 4: Frontend — engine select + report header

**Files:**
- Modify: `app/templates/index.html:62-63` (insert select before submit), `:74-136` (JS), `:146` (submit body), `:227` (listeners), `app/templates/results.html:16` (header)

**Interfaces:**
- Consumes: `SearchRequest.search_engine` (Task 1), `report.search_engine` (Task 3).
- Produces: UI select persisted in `localStorage["search_engine"]`, sent as `search_engine` in the `POST /api/search` body; results page shows the engine.

- [ ] **Step 1: Add the select** — `app/templates/index.html`, insert between `</details>` (line 61) and `<button type="submit">` (line 63):

```html
    <label>Поисковый движок
        <select id="search-engine">
            <option value="searxng">SearXNG</option>
            <option value="openserp">OpenSERP</option>
        </select>
    </label>
```

- [ ] **Step 2: Add JS helpers** — `app/templates/index.html`, after the `const LLM_STORAGE_KEY` line (line 75):

```js
const SEARCH_ENGINE_STORAGE_KEY = 'search_engine';

function searchEngineLoad() {
    const saved = localStorage.getItem(SEARCH_ENGINE_STORAGE_KEY);
    if (saved === 'openserp' || saved === 'searxng') {
        document.getElementById('search-engine').value = saved;
    }
}

function searchEngineSave() {
    localStorage.setItem(SEARCH_ENGINE_STORAGE_KEY, document.getElementById('search-engine').value);
}
```

- [ ] **Step 3: Include in the submit body** — in the `data` object (after `llm_settings: llmCollectSettings(),`, line 146):

```js
        search_engine: document.getElementById('search-engine').value,
```

- [ ] **Step 4: Wire listeners** — at the end of the script (after `llmLoadSettings();`, line 227):

```js
document.getElementById('search-engine').addEventListener('change', searchEngineSave);
searchEngineLoad();
```

- [ ] **Step 5: Report header** — `app/templates/results.html`, after the `Ключевые слова` line (line 16):

```html
<p><strong>Поисковый движок:</strong> {{ report.search_engine or 'searxng' }}</p>
```

- [ ] **Step 6: Verify template markers** — run:

```
cd cultural-history-app
.\venv\Scripts\python.exe -c "import pathlib; base = pathlib.Path('app/templates'); idx = base.joinpath('index.html').read_text(encoding='utf-8'); res = base.joinpath('results.html').read_text(encoding='utf-8'); assert 'id=\"search-engine\"' in idx; assert 'value=\"openserp\"' in idx; assert 'search_engine:' in idx; assert 'searchEngineLoad()' in idx; assert 'report.search_engine' in res; print('TEMPLATE: PASS')"
```

Expected: `TEMPLATE: PASS`

- [ ] **Step 7: Commit**

```bash
git add cultural-history-app/app/templates/index.html cultural-history-app/app/templates/results.html
git commit -m "feat: search engine selector in UI and report header"
```

---

### Task 5: Deployment — docker-compose, .env.example, AGENTS.md

**Files:**
- Modify: `cultural-history-app/docker-compose.yml`, `cultural-history-app/.env.example`, `AGENTS.md`

**Interfaces:**
- Produces: `openserp` compose service (port 7000) reachable from `app` as `http://openserp:7000`; `OPENSERP_BASE_URL`, `SEARCH_MAX_PAGES`, `OPENSERP_RESULTS_LIMIT` env for `app`; `.env.example` documents `OPENSERP_BASE_URL`, `OPENSERP_ENGINES`, `OPENSERP_MODE`, `SEARCH_MAX_PAGES`, `OPENSERP_RESULTS_LIMIT`.

- [ ] **Step 1: Add the OpenSERP service** — `cultural-history-app/docker-compose.yml`, after the `searxng` service block:

```yaml
  openserp:
    image: karust/openserp
    container_name: openserp
    ports:
      - "7000:7000"
    restart: unless-stopped
```

- [ ] **Step 2: Update the `app` service** — in the `environment:` block add:

```yaml
      - OPENSERP_BASE_URL=http://openserp:7000
      - SEARCH_MAX_PAGES=2
      - OPENSERP_RESULTS_LIMIT=50
```

and add `openserp` to `depends_on`:

```yaml
    depends_on:
      - searxng
      - openserp
```

- [ ] **Step 3: Update `.env.example`** — append after `# LM_STUDIO_MODEL=...`:

```
# OPENSERP_BASE_URL=http://localhost:7000
# OPENSERP_ENGINES=google,yandex,duckduckgo
# OPENSERP_MODE=balanced
# SEARCH_MAX_PAGES=1
# OPENSERP_RESULTS_LIMIT=30
```

- [ ] **Step 4: Update AGENTS.md** — under the `app/search.py` bullet in Architecture notes, after "sorts results by heuristic source type (UGC first)", append:

```
; search backend is selectable per request (SearXNG or OpenSERP megasearch) via `SearchRequest.search_engine`, stored on the task, and shown in the report header; pagination controlled by `SEARCH_MAX_PAGES` (SearXNG) and `OPENSERP_RESULTS_LIMIT` (OpenSERP)
```

- [ ] **Step 5: Validate compose YAML with venv PyYAML** — run:

```
cd cultural-history-app
.\venv\Scripts\python.exe -c "import yaml; d = yaml.safe_load(open('docker-compose.yml', encoding='utf-8')); assert 'openserp' in d['services']; assert 'OPENSERP_BASE_URL' in d['services']['app']['environment'][0] or any('OPENSERP_BASE_URL' in e for e in d['services']['app']['environment']); assert 'openserp' in d['services']['app']['depends_on']; print('COMPOSE: PASS')"
```

Expected: `COMPOSE: PASS`

- [ ] **Step 6: Commit**

```bash
git add cultural-history-app/docker-compose.yml cultural-history-app/.env.example AGENTS.md
git commit -m "feat: deploy OpenSERP alongside SearXNG and document config"
```

---

### Task 6: End-to-end verification and deployment checklist

**Files:**
- Throwaway: `C:\Temp\opencode\manual_test_search_e2e.py` (create, NOT committed)
- Ledger: `.superpowers/sdd/2026-08-09-search-engine-selector/` (append results)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: verified proof that a full `run_analysis` with `search_engine="openserp"` produces results end-to-end (search → scrape → LLM → Result rows) and that `SEARCH_MAX_PAGES=2` makes the SearXNG client issue `pageno=2`.

- [ ] **Step 1: Write the e2e throwaway script** — create `C:\Temp\opencode\manual_test_search_e2e.py`:

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

db = Path(r"C:\Temp\opencode\search_e2e_test.db")
if db.exists():
    db.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"

import asyncio
from app.database import init_db, async_session
from app.models import Task
from app import analyzer as analyzer_mod

asyncio.run(init_db())

async def seed_task():
    async with async_session() as s:
        s.add(Task(id="e1", object_name="Объект", keywords="впечатления", search_engine="openserp"))
        await s.commit()

asyncio.run(seed_task())

# NOTE: the Task is seeded with search_engine="openserp" because run_analysis
# forwards but does NOT persist search_engine (api_search persists it). The
# assert below then proves the seeded value survives run_analysis untouched,
# and `seen["engine"] == "openserp"` proves the forwarding.

seen = {}

async def fake_search_urls(object_name, keywords, engine="searxng"):
    seen["engine"] = engine
    seen["n_queries"] = len(
        __import__("app.search", fromlist=["build_queries"]).build_queries(object_name, keywords)
    )
    return [
        {"url": "https://blog.ru/p1", "title": "Отзыв", "source_type": "ugc"},
        {"url": "https://blog.ru/p2", "title": "Блог", "source_type": "blog"},
    ]

async def fake_fetch_and_analyze(*args, **kwargs):
    return {"mentions_object": True, "has_keyword": True,
            "keyword_found": "впечатления", "source_type": "blog",
            "relevance_score": 0.8}

orig_search = analyzer_mod.search_urls
orig_fetch = analyzer_mod.fetch_and_analyze
analyzer_mod.search_urls = fake_search_urls
analyzer_mod.fetch_and_analyze = fake_fetch_and_analyze
try:
    asyncio.run(analyzer_mod.run_analysis("e1", "Объект", "впечатления", None, None, "openserp"))
finally:
    analyzer_mod.search_urls = orig_search
    analyzer_mod.fetch_and_analyze = orig_fetch

assert seen.get("engine") == "openserp", seen
assert seen.get("n_queries", 0) >= 2, seen

from app.models import Result
from sqlalchemy import select

async def verify():
    async with async_session() as s:
        task = await s.get(Task, "e1")
        assert task.search_engine == "openserp"
        assert task.status == "completed"
        rows = (await s.execute(select(Result).where(Result.task_id == "e1"))).scalars().all()
        assert len(rows) == 2
        assert all(r.mentions_object for r in rows)

asyncio.run(verify())

print("SEARCH_E2E: PASS (run_analysis with engine=openserp)")
```

- [ ] **Step 2: Run the e2e twice consecutively** — the DB self-clean makes both runs genuine:

```
cd cultural-history-app
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_search_e2e.py
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_search_e2e.py
```

Expected: `SEARCH_E2E: PASS` twice.

- [ ] **Step 3: Verify SearXNG multi-page behavior** — extend verification with `SEARCH_MAX_PAGES=2`; run:

```
cd cultural-history-app
$env:SEARCH_MAX_PAGES = "2"
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_search_engine.py
```

Expected: still `SEARCH_ENGINE_DISPATCH: PASS` / `OPENSERP_PAGINATION: PASS` (the dispatcher path is unaffected; the pageno loop is covered by the for-the-record test `test_search_urls_defaults_to_searxng` asserting `pageno=1`).

- [ ] **Step 4: Full import sanity on the merged tree**

```
.\venv\Scripts\python.exe -c "from app.main import app; from app.search import search_urls, _search_openserp, _search_searxng; from app.schemas import SearchRequest; from app.report import build_report; print('FULL_IMPORT: PASS')"
```

Expected: `FULL_IMPORT: PASS`

- [ ] **Step 5: Record results in the SDD ledger**

Append to `.superpowers/sdd/2026-08-09-search-engine-selector/progress.md` the task-by-task outcome (each task's verification output and commit hash), the e2e double-PASS, and the OpenSERP v2 endpoint/params actually used.

- [ ] **Step 6: Final whole-branch review** — generate `git diff` from the pre-feature base to `HEAD` and dispatch a code reviewer (see `requesting-code-review` skill). Fix any Critical/Important findings, then present the finishing options.

---

## Self-Review Notes

- **Spec coverage:** selectable engine (Task 2 dispatcher + Task 3 chain + Task 4 UI), record in task (Task 1 column + Task 3 persist + Task 4 header), no-fallback behavior (Task 2 per-query catch preserved), pagination (Task 2 loops + Task 1 config + Task 5 env), deployment (Task 5), testing (Tasks 1-6).
- **Backward compatibility:** `search_engine` defaults to `"searxng"` everywhere; `search_max_pages=1` reproduces the single-page SearXNG behavior; existing tests keep passing semantics.
- **Type consistency:** `search_urls(object_name, keywords, engine=...)` used in Task 3 matches Task 2's signature; `run_analysis(..., search_engine=...)` positional order matches `main.py`'s add_task call; config field names match env var names (`OPENSERP_*`, `SEARCH_MAX_PAGES`).
