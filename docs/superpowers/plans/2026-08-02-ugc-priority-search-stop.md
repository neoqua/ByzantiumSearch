# UGC-Priority Search + Stop Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the search pipeline so UGC sources (blogs, forums, reviews, social media) are prioritized over official sites and travel agencies, and add a "stop analysis" button that marks a task `stopped` and shows partial results.

**Architecture:** Extend `app/search.py` to (a) expand queries with UGC-marker words and (b) classify each result by heuristic domain/URL/title markers, sorting UGC first and demoting official/agency (all results kept). A new pure-function module `app/source_type.py` holds the heuristics. The LLM already runs per-URL, so its prompt additionally returns a definitive `source_type` stored in the `results` table. The stop feature is a flag in `_progress_store` checked by `run_analysis` between iterations; a new `POST /api/tasks/{id}/stop` endpoint sets it, the task is marked `stopped`, and SSE emits `done` so the report page shows a banner with partial results.

**Tech Stack:** Python 3.13, FastAPI, httpx, SQLAlchemy async + aiosqlite, Jinja2, SearXNG JSON API, pytest (files only — pytest hangs on this machine, see Global Constraints).

## Global Constraints

- **Do NOT run `python -m pytest`** — it hangs on this machine. Write pytest files for the record, but verify every task with the venv python directly via `python -c` or a throwaway script in `C:\Temp\opencode` that monkeypatches `httpx.AsyncClient` (pattern: `C:\Temp\opencode\manual_test_search.py`).
- Venv python: `cultural-history-app\.venv\Scripts\python.exe`; run from `cultural-history-app` dir (script must `sys.path.insert(0, 'F:\\VisuallStudioProjects\\ByzantiumSearch\\cultural-history-app')`).
- Commit after each task to `master` (user does not want a feature branch; do not create one).
- Do not commit `.env`, `data/`, `.superpowers/`, `test_tmp.py`, `описание.txt`.
- No CI/linting configured; keep code style consistent with existing files (no type hints in `config.py` only; docstrings optional).
- LLM: `max_tokens=256` stays; new `source_type` field must fit in that budget (single short token).
- All results must be kept (no hard URL limit) — UGC only changes ordering, not the result set.

---

### Task 1: Source-type heuristic classifier

**Files:**
- Create: `cultural-history-app/app/source_type.py`
- Test: `cultural-history-app/tests/test_source_type.py`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `classify_source(url: str, title: str) -> str` — returns one of `"ugc"`, `"official"`, `"agency"`, `"unknown"`.
  - `SOURCE_PRIORITY: dict[str, int]` — `{"ugc": 0, "unknown": 1, "official": 2, "agency": 3}` (lower = higher rank).
  - `UGC_QUERY_MARKERS: list[str]` — `["отзывы", "блог", "форум", "впечатления"]`.

- [ ] **Step 1: Write the failing test**

`cultural-history-app/tests/test_source_type.py`:

```python
from app.source_type import classify_source, SOURCE_PRIORITY


def test_ugc_domain():
    assert classify_source("https://user123.livejournal.com/1200.html", "") == "ugc"
    assert classify_source("https://otzovik.com/reviews/obj123/", "") == "ugc"


def test_ugc_url_marker():
    assert classify_source("https://example.com/otzyvy/123/", "Читать") == "ugc"
    assert classify_source("https://example.com/forum/thread/1", "Тема") == "ugc"


def test_ugc_title_marker():
    assert classify_source("https://example.com/123", "Отзыв о поездке") == "ugc"
    assert classify_source("https://example.com/123", "Блог про путешествия") == "ugc"


def test_official_domain():
    assert classify_source("https://hws.gov.ru/", "Официальный сайт") == "official"
    assert classify_source("https://example-museum.ru/", "Музей") == "official"


def test_official_title_marker():
    assert classify_source("https://example.com/", "Официальный сайт объекта") == "official"


def test_agency_title_marker():
    assert classify_source("https://example.com/", "Турагентство Сказка") == "agency"
    assert classify_source("https://example.com/", "Туроператор Экскурсии") == "agency"


def test_unknown():
    assert classify_source("https://news-site.ru/article/1", "Новости") == "unknown"


def test_priority_order():
    assert SOURCE_PRIORITY["ugc"] < SOURCE_PRIORITY["unknown"] < SOURCE_PRIORITY["official"] < SOURCE_PRIORITY["agency"]
```

- [ ] **Step 2: Verify test fails**

Run:
`.\venv\Scripts\python.exe -c "from app.source_type import classify_source; print(classify_source('https://user123.livejournal.com/1200.html', ''))"`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.source_type'`.

- [ ] **Step 3: Write the implementation**

`cultural-history-app/app/source_type.py`:

```python
from urllib.parse import urlparse

SOURCE_PRIORITY = {"ugc": 0, "unknown": 1, "official": 2, "agency": 3}

UGC_QUERY_MARKERS = ["отзывы", "блог", "форум", "впечатления"]

_UGC_DOMAIN_MARKERS = (
    "livejournal.com", "lj.ru", "otzovik.com", "irecommend.ru",
    "dzen.ru", "pikabu.ru", "tripadvisor.ru", "tripadvisor.com",
    "vk.com", "vkontakte.ru", "t.me", "blogspot.com", "blogspot.ru",
    "tumblr.com", "drive2.ru", "otzyv.ru", "forum", "sibmama.ru",
    "yaplakal.com", "fishki.net", "e1.ru",
)

_UGC_URL_MARKERS = ("/blog", "/forum", "/otzyv", "/reviews", "/comments", "/obzor")

_UGC_TITLE_MARKERS = (
    "отзыв", "блог", "форум", "впечатления", "дневник",
    "рассказ", "путешеств", "поездк", "посетил", "впечатлен",
)

_OFFICIAL_URL_MARKERS = (".gov", "museum", "министерство", "правительство")

_OFFICIAL_TITLE_MARKERS = (
    "официальный сайт", "официальный портал", "официальный",
    "государств", "правительство", "министерство",
)

_AGENCY_TITLE_MARKERS = (
    "турагент", "туроператор", "турфирм", "купить тур",
    "бронирование", "туры от", "экскурсии от", "агентств",
)


def classify_source(url: str, title: str) -> str:
    url_l = url.lower()
    host = urlparse(url_l).netloc
    title_l = (title or "").lower()

    if any(m in host for m in _UGC_DOMAIN_MARKERS):
        return "ugc"
    if any(m in url_l for m in _UGC_URL_MARKERS):
        return "ugc"
    if any(m in title_l for m in _UGC_TITLE_MARKERS):
        return "ugc"

    if any(m in title_l for m in _AGENCY_TITLE_MARKERS):
        return "agency"

    if any(m in host for m in _OFFICIAL_URL_MARKERS):
        return "official"
    if any(m in title_l for m in _OFFICIAL_TITLE_MARKERS):
        return "official"

    return "unknown"
```

- [ ] **Step 4: Verify tests pass**

Run the whole test file content via venv python:

```powershell
.\venv\Scripts\python.exe -c "import tests.test_source_type as t" 2>&1
```

If that fails because `tests` is not a package, instead run:

```powershell
.\venv\Scripts\python.exe -c "from app.source_type import classify_source, SOURCE_PRIORITY; assert classify_source('https://user123.livejournal.com/1200.html','')=='ugc'; assert classify_source('https://example.com/otzyvy/123/','')=='ugc'; assert classify_source('https://example.com/123','Отзыв о поездке')=='ugc'; assert classify_source('https://hws.gov.ru/','')=='official'; assert classify_source('https://example.com/','Турагентство Сказка')=='agency'; assert classify_source('https://news-site.ru/article/1','Новости')=='unknown'; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/source_type.py cultural-history-app/tests/test_source_type.py
git commit -m "feat: heuristic source-type classifier for UGC-priority search"
```

---

### Task 2: Search query expansion + classification + sorting

**Files:**
- Modify: `cultural-history-app/app/search.py`
- Test: `cultural-history-app/tests/test_search.py`

**Interfaces:**
- Consumes: `app.source_type.classify_source`, `app.source_type.SOURCE_PRIORITY`, `app.source_type.UGC_QUERY_MARKERS`.
- Produces: `search_urls(object_name: str, keywords: list[str]) -> list[dict]` — returns `[{"url": str, "title": str, "source_type": str}, ...]`, deduped by URL, sorted UGC-first (stable).

- [ ] **Step 1: Write the failing test**

Replace `cultural-history-app/tests/test_search.py`:

```python
import pytest
import httpx
from app.search import search_urls, build_queries


def test_build_queries_contains_ugc_markers():
    queries = build_queries("TestObject", ["keyword1"])
    assert "TestObject" in queries
    assert "TestObject keyword1" in queries
    assert "TestObject отзывы" in queries
    assert "TestObject блог" in queries
    assert "TestObject форум" in queries
    assert "TestObject впечатления" in queries


@pytest.mark.asyncio
async def test_search_urls_returns_sorted_results(httpx_mock):
    def respond(request):
        q = request.url.params["q"]
        return httpx.Response(200, json={"results": [
            {"url": f"https://example.com/{q.replace(' ', '_')}", "title": q},
        ]})

    httpx_mock.add_callback(respond)

    results = await search_urls("TestObject", ["keyword1"])
    assert len(results) == len(build_queries("TestObject", ["keyword1"]))
    assert any(r["source_type"] == "ugc" for r in results)


@pytest.mark.asyncio
async def test_search_urls_prioritizes_ugc(httpx_mock):
    def respond(request):
        q = request.url.params["q"]
        if q == "TestObject":
            return httpx.Response(200, json={"results": [
                {"url": "https://example.com/", "title": "Турагентство"},
                {"url": "https://user.livejournal.com/1", "title": "Запись"},
            ]})
        return httpx.Response(200, json={"results": []})

    httpx_mock.add_callback(respond)

    results = await search_urls("TestObject", [])
    assert results[0]["source_type"] == "ugc"
    assert results[1]["source_type"] == "agency"


@pytest.mark.asyncio
async def test_search_urls_deduplicates(httpx_mock):
    def respond(request):
        return httpx.Response(200, json={"results": [
            {"url": "https://example.com/dup", "title": "Dup"},
            {"url": "https://example.com/new", "title": "New"},
        ]})

    httpx_mock.add_callback(respond)

    results = await search_urls("Test", ["kw"])
    assert len(results) == 2
```

- [ ] **Step 2: Verify test fails**

Run:
`.\venv\Scripts\python.exe -c "from app.search import build_queries; print(build_queries('TestObject', ['keyword1']))"`

Expected: FAIL — `ImportError: cannot import name 'build_queries'`.

- [ ] **Step 3: Write the implementation**

`cultural-history-app/app/search.py` (full replace):

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


async def search_urls(object_name: str, keywords: List[str]) -> List[Dict[str, str]]:
    queries = build_queries(object_name, keywords)

    seen_urls: set = set()
    results: List[Dict[str, str]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                params = {
                    "q": query,
                    "format": "json",
                    "language": "ru-RU",
                    "categories": "general",
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
                        results.append({
                            "url": url,
                            "title": item.get("title", ""),
                            "source_type": classify_source(url, item.get("title", "")),
                        })
            except Exception as e:
                logger.warning("Search query '%s' failed: %s", query, e)

    results.sort(key=_sort_key)
    return results
```

- [ ] **Step 4: Verify tests pass**

Throwaway script `C:\Temp\opencode\manual_test_search_ugc.py` (adapt from `manual_test_search.py`): monkeypatch `app.search.httpx.AsyncClient` with a `MockClient` that answers every URL in `build_queries("TestObject", ["keyword1"])` plus the plain-object query, then assert sorted order and dedup. Run:

```powershell
.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_search_ugc.py
```

Expected: prints `All tests PASSED!`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/search.py cultural-history-app/tests/test_search.py
git commit -m "feat: UGC-priority query expansion and result sorting in search"
```

---

### Task 3: LLM source_type field

**Files:**
- Modify: `cultural-history-app/app/llm.py`
- Test: `cultural-history-app/tests/test_llm.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `analyze_text_with_retry(...)` returns dict that now includes `source_type` in `{"blog","forum","social","official","agency","other"}`; `_coerce_result` normalizes missing/invalid values to `"other"`.

- [ ] **Step 1: Write the failing test**

Add to `cultural-history-app/tests/test_llm.py`:

```python
def test_build_prompt_contains_source_type():
    prompt = _build_prompt("Test Monastery", ["Byzantium"], "Title", "Text")
    assert "source_type" in prompt
    assert "blog/forum/social/official/agency/other" in prompt


def test_coerce_result_source_type_valid():
    result = _coerce_result({"source_type": "blog"})
    assert result["source_type"] == "blog"


def test_coerce_result_source_type_invalid_defaults():
    result = _coerce_result({"source_type": "музей"})
    assert result["source_type"] == "other"


def test_coerce_result_source_type_missing_defaults():
    result = _coerce_result({})
    assert result["source_type"] == "other"
```

- [ ] **Step 2: Verify test fails**

Run:
`.\venv\Scripts\python.exe -c "from app.llm import _coerce_result; print(_coerce_result({}).get('source_type', 'MISSING'))"`

Expected: prints `MISSING`.

- [ ] **Step 3: Write the implementation**

Modify `cultural-history-app/app/llm.py`:

`_build_prompt`: after the `relevance_score` line, add:

```python
        '  "source_type": "blog/forum/social/official/agency/other"\n'
```

`_coerce_result`: add after the relevance coercion line:

```python
    allowed_source_types = {"blog", "forum", "social", "official", "agency", "other"}
    source_type = result.get("source_type")
    if source_type not in allowed_source_types:
        source_type = "other"
    result["source_type"] = source_type
```

Fallback dict in `analyze_text_with_retry`: add `"source_type": "other",`.

- [ ] **Step 4: Verify tests pass**

Run:
`.\venv\Scripts\python.exe -c "from app.llm import _coerce_result, _build_prompt; assert _coerce_result({'source_type':'blog'})['source_type']=='blog'; assert _coerce_result({'source_type':'музей'})['source_type']=='other'; assert _coerce_result({})['source_type']=='other'; assert 'source_type' in _build_prompt('X',['y'],'T','t'); print('OK')"`

Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/llm.py cultural-history-app/tests/test_llm.py
git commit -m "feat: LLM returns authoritative source_type per URL"
```

---

### Task 4: DB column, schemas, report, scraper passthrough

**Files:**
- Modify: `cultural-history-app/app/models.py`, `cultural-history-app/app/schemas.py`, `cultural-history-app/app/report.py`, `cultural-history-app/app/scraper.py`, `cultural-history-app/app/database.py`
- Test: `cultural-history-app/tests/test_api.py` (add one schema assertion)

**Interfaces:**
- Consumes: `llm` result dict with `source_type`.
- Produces:
  - `models.Result.source_type: Column(String, nullable=True)`.
  - `schemas.AnalysisResult.source_type: Optional[str] = None`.
  - `schemas.ReportData.status: str = "completed"`.
  - `database.init_db()` idempotently adds `source_type` column to existing `results` table.
  - `scraper.fetch_and_analyze` passes `source_type` through (default `"other"` when fetch fails).

- [ ] **Step 1: Write the failing test**

Add to `cultural-history-app/tests/test_api.py`:

```python
from app.schemas import ReportData, AnalysisResult


def test_report_data_accepts_status():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[], status="stopped",
    )
    assert r.status == "stopped"


def test_analysis_result_accepts_source_type():
    r = AnalysisResult(url="https://x", source_type="blog")
    assert r.source_type == "blog"
```

- [ ] **Step 2: Verify test fails**

Run:
`.\venv\Scripts\python.exe -c "from app.schemas import ReportData; ReportData(task_id='t',object_name='o',keywords='k',total_mentions=0,mentions_with_keyword=0,keyword_percentage=0.0,results=[],status='stopped')"`

Expected: FAIL — `TypeError` (unexpected keyword `status`).

- [ ] **Step 3: Write the implementation**

`models.py` — add after `author_location` column in `Result`:

```python
    source_type = Column(String, nullable=True)
```

`schemas.py` — add to `AnalysisResult`:

```python
    source_type: Optional[str] = None
```

Add to `ReportData`:

```python
    status: str = "completed"
```

`report.py` — in `build_report`, pass `status` to `ReportData`:

```python
        status=task.status,
```

`scraper.py` — in `fetch_and_analyze`'s early-return dict (fetch-fail branch), add:

```python
            "source_type": "other",
```

and after `llm_result = await analyze_text_with_retry(...)`, ensure the key exists:

```python
    llm_result.setdefault("source_type", "other")
```

`database.py` — extend `init_db` with an idempotent migration (module-level `text` import so both functions see it):

```python
from sqlalchemy import text


async def init_db():
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_results_source_type)


def _ensure_results_source_type(sync_conn):
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    if "results" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("results")}
    if "source_type" not in cols:
        sync_conn.execute(text("ALTER TABLE results ADD COLUMN source_type VARCHAR(20)"))
```

- [ ] **Step 4: Verify tests pass**

Run:
`.\venv\Scripts\python.exe -c "from app.schemas import ReportData, AnalysisResult; r=ReportData(task_id='t',object_name='o',keywords='k',total_mentions=0,mentions_with_keyword=0,keyword_percentage=0.0,results=[],status='stopped'); assert r.status=='stopped'; a=AnalysisResult(url='https://x',source_type='blog'); assert a.source_type=='blog'; print('OK')"`

Then verify migration against a throwaway DB:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///C:/Temp/opencode/mig_test.db"
.\venv\Scripts\python.exe -c "import asyncio; from app.database import init_db; asyncio.run(init_db()); from sqlalchemy import create_engine; e=create_engine('sqlite:///C:/Temp/opencode/mig_test.db'); print('source_type' in {c['name'] for c in __import__('sqlalchemy').inspect(e).get_columns('results')})"
```

Expected: prints `OK`, then `True`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/models.py cultural-history-app/app/schemas.py cultural-history-app/app/report.py cultural-history-app/app/scraper.py cultural-history-app/app/database.py cultural-history-app/tests/test_api.py
git commit -m "feat: store source_type and task status in report schemas"
```

---

### Task 5: Stop endpoint + analyzer stop flag

**Files:**
- Modify: `cultural-history-app/app/analyzer.py`, `cultural-history-app/app/main.py`
- Test: `cultural-history-app/tests/test_api.py`

**Interfaces:**
- Consumes: `_progress_store` (existing), `Task`, `Result`.
- Produces:
  - `POST /api/tasks/{task_id}/stop` → `{"status": "stopping"}` or 404.
  - `run_analysis` sets task status `"stopped"` and `_progress_store[task_id]["status"] = "stopped"` when the stop flag is set between URL iterations.
  - SSE `done` event fires for both `"completed"` and `"stopped"`.
  - `Result.source_type` is persisted from `llm_data["source_type"]` (fallback `"other"`) at row creation — completes the Task 4 gap (Task 4 added the column + scraper passthrough but never wrote the field).

- [ ] **Step 1: Write the failing test**

Add to `cultural-history-app/tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_stop_returns_stopping(api_client):
    resp = await api_client.post("/api/tasks/nonexistent/stop")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stop_sets_flag(api_client):
    resp = await api_client.post("/api/search", json={
        "object_name": "Obj", "keywords": "kw",
    })
    task_id = resp.json()["task_id"]
    stop = await api_client.post(f"/api/tasks/{task_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopping"
    from app.analyzer import _progress_store
    assert _progress_store[task_id]["stop_requested"] is True
```

- [ ] **Step 2: Verify test fails**

Run:
`.\venv\Scripts\python.exe C:\Temp\opencode\manual_probe.py` (throwaway: call `POST /api/tasks/nonexistent/stop` via ASGI transport).

Expected: FAIL — 404 route not found (or 405).

- [ ] **Step 3: Write the implementation**

`main.py` — add endpoint after `api_search`:

```python
@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    progress = get_progress(task_id)
    if progress is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    progress["stop_requested"] = True
    return {"status": "stopping"}
```

`main.py` — SSE `event_stream`: change the completed branch to:

```python
            if status in ("completed", "stopped"):
                yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'redirect': f'/results/{task_id}'})}\n\n"
                break
```

`analyzer.py` — in `run_analysis`, before the per-URL loop, init flag handling. At the top of the `for entry in all_urls:` loop body add:

```python
                if _progress_store[task_id].get("stop_requested"):
                    stopped = True
                    break
```

Also persist `source_type` on the `Result` row (Task 4 gap): add `source_type=llm_data.get("source_type", "other"),` to the `Result(...)` constructor in `run_analysis` (after `raw_text_hash=...`).

Define `stopped = False` right before the loop. After the loop, replace the status-update block:

```python
            task = await session.get(Task, task_id)
            if task:
                task.status = "stopped" if stopped else "completed"
                task.completed_at = datetime.utcnow()
                await session.commit()

        _progress_store[task_id]["status"] = "stopped" if stopped else "completed"
```

- [ ] **Step 4: Verify tests pass**

Throwaway script `C:\Temp\opencode\manual_test_stop.py`: build an ASGI client, create a task via `/api/search` with `run_analysis` monkeypatched to a coroutine that iterates while checking the flag (simulate), then `POST /stop` and assert 200/`stopping` and `_progress_store` flag. Run and expect `PASS`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/analyzer.py cultural-history-app/app/main.py cultural-history-app/tests/test_api.py
git commit -m "feat: stop analysis endpoint and stopped task status"
```

---

### Task 6: Frontend — stop button + report banner + source column

**Files:**
- Modify: `cultural-history-app/app/templates/index.html`, `cultural-history-app/app/templates/results.html`

**Interfaces:**
- Consumes: `POST /api/tasks/{task_id}/stop`; SSE `done` event; `report.status`, `report.results[].source_type`.

- [ ] **Step 1: Write the frontend changes**

`index.html` — inside `<div id="progress">`, after the progress-text div, add a stop button:

```html
    <button type="button" id="stop-btn" style="display:none;">Остановить анализ</button>
```

In the JS, after `evtSource = new EventSource(...)` is created, show the button and wire it:

```js
    const stopBtn = document.getElementById('stop-btn');
    stopBtn.style.display = 'inline-block';
    stopBtn.onclick = async function() {
        stopBtn.disabled = true;
        stopBtn.textContent = 'Остановка...';
        await fetch(`/api/tasks/${result.task_id}/stop`, {method: 'POST'});
    };
```

In the `done` listener, hide the button:

```js
    evtSource.addEventListener('done', function(event) {
        evtSource.close();
        stopBtn.style.display = 'none';
        window.location.href = JSON.parse(event.data).redirect;
    });
```

`results.html` — after the `<h1>`, add a stopped banner:

```html
{% if report.status == 'stopped' %}
<div class="error">Анализ остановлен пользователем. Показаны частичные результаты.</div>
{% endif %}
```

Add a "Тип источника" column: in the `<thead>`, after `<th>Заголовок</th>` add `<th>Источник</th>`, and in the row after the title cell add `<td>{{ r.source_type or '—' }}</td>`.

- [ ] **Step 2: Verify**

Run the app with venv uvicorn (if aiohttp import does not hang) or at minimum render both templates via Jinja2:

```powershell
.\venv\Scripts\python.exe -c "from app.main import templates; print('templates OK')"
```

Then open `http://localhost:8000`, run an analysis, click «Остановить анализ», confirm redirect to report with banner and source column.

- [ ] **Step 3: Commit**

```bash
git add cultural-history-app/app/templates/index.html cultural-history-app/app/templates/results.html
git commit -m "feat: stop button on progress page and source-type column in report"
```

---

### Task 7: End-to-end verification

**Files:**
- Create: `C:\Temp\opencode\manual_test_e2e.py` (throwaway, not committed)

**Interfaces:**
- Consumes: full app.

- [ ] **Step 1: Write the e2e script**

Script that:
1. Sets `DATABASE_URL` to a throwaway DB.
2. Monkeypatches `app.main.run_analysis` with a coroutine that, per URL, increments `_progress_store` and checks the stop flag.
3. Uses `ASGITransport` to: POST `/api/search`, assert 200; POST `/stop`, assert `stopping`; assert `_progress_store[task_id]["stop_requested"] is True`; set `_progress_store[task_id]["status"] = "stopped"`; GET `/api/tasks/{id}/progress` (buffered) and assert the `done` event redirect contains `/results/{id}`.
4. GET `/results/{id}` and assert the stopped banner text appears and status `stopped` is in the JSON at `/api/tasks/{id}/results`.

Run:
`.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_e2e.py`

Expected: prints `All tests PASSED!`.

- [ ] **Step 2: Confirm all commits**

```bash
git log --oneline -8
```

Expected: the seven new feature commits (Tasks 1–6) on top of `master`; `git status` clean except `.superpowers/`, `cultural-history-app/test_tmp.py`, `описание.txt`.

- [ ] **Step 3: (Optional) Update AGENTS.md**

Add a line under Known issues or Architecture notes: search now expands queries with UGC markers (`отзывы, блог, форум, впечатления`) and sorts results by heuristic source type (UGC first); LLM returns authoritative `source_type`; stop endpoint marks task `stopped`.

Commit only if added:
```bash
git add AGENTS.md
git commit -m "docs: note UGC-priority search and stop feature"
```

---

## Self-Review Notes

- **Spec coverage:** UGC-priority (Tasks 1–2), authoritative LLM classification (Task 3), persistence/report (Task 4), stop with `stopped` status (Task 5), UI (Task 6), end-to-end (Task 7). No hard URL limit kept per user decision — results are only reordered.
- **Placeholders:** none; every code step contains full content.
- **Type consistency:** `source_type` used consistently across `search.py`, `llm.py`, `models.py`, `schemas.py`, `report.py`, templates. `status` in `ReportData` default `"completed"`; analyzer sets `"stopped"`/`"completed"`. `build_queries` returns list of str; `search_urls` returns list of dict with `url`, `title`, `source_type`.
