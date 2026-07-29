# Cultural History Analysis App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a web service where users enter a cultural/historical object + keywords, and get statistics on how many web mentions reference those keywords, with LLM analysis of each page.

**Architecture:** Python FastAPI backend, SQLite storage, SearXNG for web search, Llama 3.1-8B (LM Studio) for text analysis. SSE for live progress. Jinja2 templates for UI.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy + SQLite, aiohttp, httpx, BeautifulSoup4, Jinja2, SearXNG (Docker)

## Global Constraints

- LM Studio runs on localhost:1234 with OpenAI-compatible API at `/v1/chat/completions`
- SearXNG runs in Docker on localhost:8888
- All LLM calls use temperature=0.1, max_tokens=256
- Python 3.11 minimum
- No external paid API keys required (except Yandex XML for SearXNG)

---

### File Structure

```
cultural-history-app/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, mount routes
│   ├── config.py            # Settings via pydantic-settings (or os.getenv)
│   ├── database.py          # SQLAlchemy engine + session dependency
│   ├── models.py            # ORM models: Task, Result, UrlCache
│   ├── schemas.py           # Pydantic models: SearchRequest, TaskStatus, AnalysisResult, ReportData
│   ├── search.py            # SearXNG JSON API client
│   ├── scraper.py           # HTML download + text extraction
│   ├── llm.py               # LM Studio API client
│   ├── analyzer.py          # Orchestrator: background task management
│   ├── report.py            # Report data assembly
│   └── templates/
│       ├── base.html
│       ├── index.html
│       └── results.html
├── searxng/
│   └── settings.yml         # SearXNG config (Yandex + Google engines)
├── docker-compose.yml       # SearXNG service
├── requirements.txt
└── .env
```

---

### Task 1: Scaffolding — config, database, models, schemas

**Files:**
- Create: `cultural-history-app/requirements.txt`
- Create: `cultural-history-app/.env`
- Create: `cultural-history-app/app/__init__.py`
- Create: `cultural-history-app/app/config.py`
- Create: `cultural-history-app/app/database.py`
- Create: `cultural-history-app/app/models.py`
- Create: `cultural-history-app/app/schemas.py`

**Interfaces:**
- Produces: `config.Settings` dataclass with all env vars
- Produces: `database.get_db()` async generator yielding `AsyncSession`
- Produces: `models.Task`, `models.Result`, `models.UrlCache` SQLAlchemy models
- Produces: `schemas.SearchRequest`, `schemas.TaskStatus`, `schemas.AnalysisResult`, `schemas.ReportData`

- [ ] **Step 1: Create requirements.txt**

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy[asyncio]>=2.0.25
aiosqlite>=0.20.0
aiohttp>=3.9.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0
jinja2>=3.1.0
python-multipart>=0.0.6
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-httpx>=0.30.0
```

- [ ] **Step 2: Create .env**

```
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
SEARXNG_BASE_URL=http://localhost:8888
LM_STUDIO_BASE_URL=http://localhost:1234
LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
```

- [ ] **Step 3: Create config.py**

```python
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./data/app.db"
        )
    )
    searxng_base_url: str = field(
        default_factory=lambda: os.getenv("SEARXNG_BASE_URL", "http://localhost:8888")
    )
    lm_studio_base_url: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234")
    )
    lm_studio_model: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_MODEL", "meta-llama-3.1-8b-instruct")
    )


settings = Settings()
```

- [ ] **Step 4: Create database.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 5: Create models.py**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def generate_uuid():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    object_name = Column(String, nullable=False)
    keywords = Column(String, nullable=False)
    annual_visitors = Column(Integer, nullable=True)
    manual_urls = Column(Text, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    results = relationship("Result", back_populates="task", cascade="all, delete-orphan")


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=True)
    mentions_object = Column(Boolean, default=False)
    has_keyword = Column(Boolean, default=False)
    keyword_found = Column(String, nullable=True)
    date_mentioned = Column(String, nullable=True)
    publication_date = Column(String, nullable=True)
    author_location = Column(String, nullable=True)
    relevance_score = Column(Float, default=0.0)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="results")


class UrlCache(Base):
    __tablename__ = "url_cache"

    url = Column(String, primary_key=True)
    object_name = Column(String, nullable=False)
    result_json = Column(Text, nullable=True)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 6: Create schemas.py**

```python
from pydantic import BaseModel
from typing import Optional, List


class SearchRequest(BaseModel):
    object_name: str
    keywords: str
    annual_visitors: Optional[int] = None
    manual_urls: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    status: str
    processed: int = 0
    total: int = 0
    found_keyword: int = 0
    current_url: Optional[str] = None
    current_title: Optional[str] = None


class AnalysisResult(BaseModel):
    url: str
    title: Optional[str] = None
    mentions_object: bool = False
    has_keyword: bool = False
    keyword_found: Optional[str] = None
    date_mentioned: Optional[str] = None
    publication_date: Optional[str] = None
    author_location: Optional[str] = None
    relevance_score: float = 0.0


class ReportData(BaseModel):
    task_id: str
    object_name: str
    keywords: str
    annual_visitors: Optional[int]
    total_mentions: int
    mentions_with_keyword: int
    keyword_percentage: float
    percentage_of_visitors: Optional[float]
    results: List[AnalysisResult]
```

- [ ] **Step 7: Verify imports work**

Run: `cd cultural-history-app && python -c "from app.config import settings; from app.models import Task, Result; from app.schemas import SearchRequest; print('OK')"`
Expected: OK

---

### Task 2: LLM client

**Files:**
- Create: `cultural-history-app/app/llm.py`

**Interfaces:**
- Consumes: `config.settings` — `lm_studio_base_url`, `lm_studio_model`
- Produces: `async def analyze_text(object_name: str, keywords: list[str], title: str, text: str) -> dict`

- [ ] **Step 1: Create llm.py**

```python
import json
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _build_prompt(object_name: str, keywords: list[str], title: str, text: str) -> str:
    keywords_str = ", ".join(keywords)
    return (
        f'Analyze the text below. Determine if "{object_name}" is mentioned, '
        f'if any of these keywords appear: [{keywords_str}], and extract dates and author location.\n\n'
        f"Object: {object_name}\n"
        f"Keywords: {keywords_str}\n\n"
        f"Title: {title}\n\n"
        f"Text: {text[:3000]}\n\n"
        "Respond in JSON format only:\n"
        '{\n'
        '  "mentions_object": true/false,\n'
        '  "object_name": "name from text or null",\n'
        '  "has_keyword": true/false,\n'
        '  "keyword_found": "which keyword was found or null",\n'
        '  "date_mentioned": "DD.MM.YYYY from text or null",\n'
        '  "publication_date": "DD.MM.YYYY or null",\n'
        '  "author_location": "city, country, region or null",\n'
        '  "relevance_score": 0.0-1.0\n'
        "}"
    )


def _parse_response(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON found in response: {response_text[:200]}")


async def analyze_text(
    object_name: str, keywords: list[str], title: str, text: str
) -> dict:
    prompt = _build_prompt(object_name, keywords, title, text)
    payload = {
        "model": settings.lm_studio_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 256,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        url = f"{settings.lm_studio_base_url}/v1/chat/completions"
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_response(content)


async def analyze_text_with_retry(
    object_name: str, keywords: list[str], title: str, text: str, max_retries: int = 2
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            return await analyze_text(object_name, keywords, title, text)
        except Exception as e:
            logger.warning("LLM analysis attempt %d failed: %s", attempt + 1, e)
            if attempt == max_retries:
                return {
                    "mentions_object": False,
                    "has_keyword": False,
                    "keyword_found": None,
                    "date_mentioned": None,
                    "publication_date": None,
                    "author_location": None,
                    "relevance_score": 0.0,
                }
```

- [ ] **Step 2: Write test for llm.py**

Create: `cultural-history-app/tests/test_llm.py`

```python
import json
import pytest
from app.llm import _build_prompt, _parse_response


def test_build_prompt_contains_object_and_keyword():
    prompt = _build_prompt("Test Monastery", "Byzantium", "Title", "Some text")
    assert "Test Monastery" in prompt
    assert "Byzantium" in prompt


def test_parse_response_json_object():
    data = {"mentions_object": True, "has_keyword": True, "relevance_score": 0.95}
    result = _parse_response(json.dumps(data))
    assert result["mentions_object"] is True
    assert result["relevance_score"] == 0.95


def test_parse_response_code_block():
    raw = f"```json\n{json.dumps({'mentions_object': False})}\n```"
    result = _parse_response(raw)
    assert result["mentions_object"] is False


def test_parse_response_extra_text():
    raw = f"Here is the result:\n{json.dumps({'has_keyword': True})}\nDone."
    result = _parse_response(raw)
    assert result["has_keyword"] is True


def test_parse_response_raises_on_no_json():
    with pytest.raises(ValueError):
        _parse_response("No JSON here at all")
```

- [ ] **Step 3: Run tests**

Run: `cd cultural-history-app && python -m pytest tests/test_llm.py -v`
Expected: 5 passed

---

### Task 3: Search module (SearXNG client)

**Files:**
- Create: `cultural-history-app/app/search.py`

**Interfaces:**
- Consumes: `config.settings` — `searxng_base_url`
- Produces: `async def search_urls(object_name: str, keywords: list[str]) -> list[dict]`
  Returns `[{"url": str, "title": str}, ...]`

- [ ] **Step 1: Create search.py**

```python
import logging
from typing import List, Dict
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


async def search_urls(object_name: str, keywords: List[str]) -> List[Dict[str, str]]:
    queries = [object_name]
    for kw in keywords:
        queries.append(f"{object_name} {kw}")

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
                        })
            except Exception as e:
                logger.warning("Search query '%s' failed: %s", query, e)

    return results
```

- [ ] **Step 2: Write test for search.py**

Create: `cultural-history-app/tests/test_search.py`

```python
import pytest
from app.search import search_urls


@pytest.mark.asyncio
async def test_search_urls_returns_list(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=TestObject&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/post1", "title": "Post 1"},
                {"url": "https://example.com/post2", "title": "Post 2"},
            ]
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=TestObject+keyword1&format=json&language=ru-RU&categories=general",
        json={"results": []},
    )

    results = await search_urls("TestObject", ["keyword1"])
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/post1"
    assert results[1]["url"] == "https://example.com/post2"


@pytest.mark.asyncio
async def test_search_urls_deduplicates(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=Test&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/dup", "title": "Dup"},
            ]
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=Test+kw&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/dup", "title": "Dup"},
                {"url": "https://example.com/new", "title": "New"},
            ]
        },
    )

    results = await search_urls("Test", ["kw"])
    assert len(results) == 2
```

- [ ] **Step 3: Run tests**

Run: `cd cultural-history-app && python -m pytest tests/test_search.py -v`
Expected: 2 passed

---

### Task 4: Scraper module

**Files:**
- Create: `cultural-history-app/app/scraper.py`

**Interfaces:**
- Consumes: `llm.analyze_text_with_retry()`
- Produces: `async def fetch_and_analyze(url: str, object_name: str, keywords: list[str], title: str) -> dict`

- [ ] **Step 1: Create scraper.py**

```python
import hashlib
import logging
from typing import Optional
import aiohttp
from bs4 import BeautifulSoup
from app.llm import analyze_text_with_retry

logger = logging.getLogger(__name__)


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def fetch_page_text(url: str) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status != 200:
                    logger.warning("HTTP %d for %s", resp.status, url)
                    return None
                html = await resp.text(encoding="utf-8", errors="replace")
                return extract_text(html)
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


async def fetch_and_analyze(
    url: str, object_name: str, keywords: list[str], title: str
) -> dict:
    text = await fetch_page_text(url)
    if not text:
        return {
            "url": url,
            "title": title,
            "mentions_object": False,
            "has_keyword": False,
            "keyword_found": None,
            "date_mentioned": None,
            "publication_date": None,
            "author_location": None,
            "relevance_score": 0.0,
            "raw_text_hash": None,
        }
    h = text_hash(text)
    llm_result = await analyze_text_with_retry(object_name, keywords, title, text)
    llm_result["url"] = url
    llm_result["title"] = title
    llm_result["raw_text_hash"] = h
    return llm_result
```

- [ ] **Step 2: Write test for scraper.py**

Create: `cultural-history-app/tests/test_scraper.py`

```python
import pytest
from app.scraper import extract_text, text_hash


def test_extract_text_removes_tags():
    html = "<html><body><p>Hello <b>world</b></p><script>var x=1;</script></body></html>"
    result = extract_text(html)
    assert "Hello world" in result
    assert "var x" not in result


def test_extract_text_empty():
    assert extract_text("") == ""


def test_text_hash_consistent():
    h1 = text_hash("same text")
    h2 = text_hash("same text")
    assert h1 == h2


def test_text_hash_different():
    h1 = text_hash("text a")
    h2 = text_hash("text b")
    assert h1 != h2
```

- [ ] **Step 3: Run tests**

Run: `cd cultural-history-app && python -m pytest tests/test_scraper.py -v`
Expected: 4 passed

---

### Task 5: Analyzer orchestrator

**Files:**
- Create: `cultural-history-app/app/analyzer.py`

**Interfaces:**
- Consumes: `search.search_urls()`, `scraper.fetch_and_analyze()`, DB models, `llm.analyze_text_with_retry()`
- Produces: `async def run_analysis(task_id: str, object_name: str, keywords_raw: str, manual_urls_raw: str | None)`

- [ ] **Step 1: Create analyzer.py**

```python
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Task, Result, UrlCache
from app.search import search_urls
from app.scraper import fetch_and_analyze
from app.llm import analyze_text_with_retry

logger = logging.getLogger(__name__)

# In-memory progress store: task_id -> dict
_progress_store: Dict[str, Dict[str, Any]] = {}


def get_progress(task_id: str) -> Optional[Dict[str, Any]]:
    return _progress_store.get(task_id)


def _split_keywords(keywords_raw: str):
    return [kw.strip() for kw in keywords_raw.split(",") if kw.strip()]


def _split_urls(urls_raw: Optional[str]):
    if not urls_raw:
        return []
    return [u.strip() for u in urls_raw.split("\n") if u.strip()]


async def run_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str] = None,
):
    keywords = _split_keywords(keywords_raw)
    manual_urls = _split_urls(manual_urls_raw)

    _progress_store[task_id] = {
        "status": "processing",
        "processed": 0,
        "total": 0,
        "found_keyword": 0,
        "current_url": None,
        "current_title": None,
    }

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            return
        task.status = "processing"
        await session.commit()

    # Step 1: Search
    all_urls = []
    try:
        search_results = await search_urls(object_name, keywords)
        for item in search_results:
            all_urls.append(item)
    except Exception as e:
        logger.error("Search failed: %s", e)

    # Step 2: Add manual URLs
    for url in manual_urls:
        if not any(item["url"] == url for item in all_urls):
            all_urls.append({"url": url, "title": ""})

    total = len(all_urls)
    _progress_store[task_id]["total"] = total

    processed = 0
    found_keyword = 0

    async with async_session() as session:
        for entry in all_urls:
            url = entry["url"]
            title = entry["title"]

            _progress_store[task_id].update(
                current_url=url,
                current_title=title,
            )

            # Check URL cache
            cached = await session.get(UrlCache, url)
            if cached and cached.object_name == object_name:
                llm_data = json.loads(cached.result_json) if cached.result_json else {}
            else:
                # Analyze for ALL keywords in one LLM call
                llm_data = await fetch_and_analyze(url, object_name, keywords, title)
                cache_entry = UrlCache(
                    url=url,
                    object_name=object_name,
                    result_json=json.dumps(llm_data, ensure_ascii=False),
                    raw_text_hash=llm_data.get("raw_text_hash"),
                )
                session.add(cache_entry)
                await session.commit()

            mentions = llm_data.get("mentions_object", False)
            has_kw = llm_data.get("has_keyword", False)

            if has_kw:
                found_keyword += 1

            result_entry = Result(
                task_id=task_id,
                url=url,
                title=title,
                mentions_object=mentions,
                has_keyword=has_kw,
                keyword_found=llm_data.get("keyword_found"),
                date_mentioned=llm_data.get("date_mentioned"),
                publication_date=llm_data.get("publication_date"),
                author_location=llm_data.get("author_location"),
                relevance_score=llm_data.get("relevance_score", 0.0),
                raw_text_hash=llm_data.get("raw_text_hash"),
            )
            session.add(result_entry)
            await session.commit()

            processed += 1
            _progress_store[task_id].update(
                processed=processed,
                found_keyword=found_keyword,
            )

        # Update task status
        task = await session.get(Task, task_id)
        if task:
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            await session.commit()

    _progress_store[task_id]["status"] = "completed"
```

---

### Task 6: API endpoints + report

**Files:**
- Create: `cultural-history-app/app/main.py`
- Create: `cultural-history-app/app/report.py`

**Interfaces:**
- Consumes: `analyzer.run_analysis()`, `analyzer.get_progress()`, DB models
- Produces: FastAPI app with all routes

- [ ] **Step 1: Create report.py**

```python
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Task, Result
from app.schemas import ReportData, AnalysisResult


async def build_report(task_id: str, session: AsyncSession) -> Optional[ReportData]:
    task = await session.get(Task, task_id)
    if not task:
        return None

    stmt = select(Result).where(Result.task_id == task_id)
    result_rows = (await session.execute(stmt)).scalars().all()

    total = len(result_rows)
    with_keyword = sum(1 for r in result_rows if r.has_keyword)
    keyword_pct = round((with_keyword / total * 100), 1) if total > 0 else 0.0

    visitor_pct = None
    if task.annual_visitors and task.annual_visitors > 0:
        visitor_pct = round((with_keyword / task.annual_visitors * 100), 4)

    results_list = [
        AnalysisResult(
            url=r.url,
            title=r.title,
            mentions_object=r.mentions_object,
            has_keyword=r.has_keyword,
            keyword_found=r.keyword_found,
            date_mentioned=r.date_mentioned,
            publication_date=r.publication_date,
            author_location=r.author_location,
            relevance_score=r.relevance_score or 0.0,
        )
        for r in result_rows
    ]

    return ReportData(
        task_id=task_id,
        object_name=task.object_name,
        keywords=task.keywords,
        annual_visitors=task.annual_visitors,
        total_mentions=total,
        mentions_with_keyword=with_keyword,
        keyword_percentage=keyword_pct,
        percentage_of_visitors=visitor_pct,
        results=results_list,
    )
```

- [ ] **Step 2: Create main.py**

```python
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, init_db
from app.models import Task
from app.schemas import SearchRequest
from app.analyzer import run_analysis, get_progress
from app.report import build_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Cultural History Analyzer", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/search")
async def api_search(
    body: SearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        object_name=body.object_name,
        keywords=body.keywords,
        annual_visitors=body.annual_visitors,
        manual_urls=body.manual_urls,
        status="pending",
    )
    db.add(task)
    await db.commit()

    background_tasks.add_task(
        run_analysis,
        task.id,
        body.object_name,
        body.keywords,
        body.manual_urls,
    )

    return {"task_id": task.id, "status": "pending"}


@app.get("/api/tasks/{task_id}/progress")
async def task_progress(task_id: str):
    progress = get_progress(task_id)

    async def event_stream():
        while True:
            progress = get_progress(task_id)
            if progress is None:
                yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                break
            if progress["status"] == "completed":
                yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'redirect': f'/results/{task_id}'})}\n\n"
                break

            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/tasks/{task_id}/results")
async def task_results(task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return report.model_dump()


@app.get("/results/{task_id}", response_class=HTMLResponse)
async def results_page(request: Request, task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return templates.TemplateResponse("results.html", {"request": request, "report": None, "error": "Task not found"})
    return templates.TemplateResponse("results.html", {"request": request, "report": report, "error": None})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

- [ ] **Step 3: Test API with pytest**

Create: `cultural-history-app/tests/test_api.py`

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_index_returns_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_api_search_returns_task_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/search", json={
            "object_name": "Test Monastery",
            "keywords": "keyword1, keyword2",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"
```

- [ ] **Step 4: Run tests**

Run: `cd cultural-history-app && python -m pytest tests/test_api.py -v`
Expected: 2 passed

---

### Task 7: Frontend templates

**Files:**
- Create: `cultural-history-app/app/templates/base.html`
- Create: `cultural-history-app/app/templates/index.html`
- Create: `cultural-history-app/app/templates/results.html`

- [ ] **Step 1: Create base.html**

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Анализ культурно-исторических объектов{% endblock %}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        h1 { font-size: 1.5em; margin-top: 0; }
        label { display: block; margin-top: 12px; font-weight: 600; }
        input, textarea { width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        textarea { min-height: 80px; font-family: monospace; }
        button { margin-top: 16px; padding: 10px 24px; background: #1a73e8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }
        button:hover { background: #1557b0; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; }
        .stat { display: inline-block; margin: 8px 16px 8px 0; }
        .stat-value { font-size: 1.8em; font-weight: bold; color: #1a73e8; }
        .stat-label { font-size: 0.85em; color: #666; }
        .error { color: #d32f2f; padding: 12px; background: #fdeaea; border-radius: 4px; }
        .progress-bar { width: 100%; height: 8px; background: #eee; border-radius: 4px; margin-top: 12px; overflow: hidden; }
        .progress-fill { height: 100%; background: #1a73e8; transition: width 0.3s; }
        #progress-text { margin-top: 8px; color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>
```

- [ ] **Step 2: Create index.html**

```html
{% extends "base.html" %}
{% block title %}Анализ культурно-исторических объектов{% endblock %}
{% block content %}
<h1>Анализ упоминаний культурно-исторических объектов</h1>

<form id="search-form">
    <label for="object_name">Название объекта *</label>
    <input type="text" id="object_name" name="object_name" required placeholder="Свято-Климентовский монастырь">

    <label for="keywords">Ключевые слова * (через запятую)</label>
    <input type="text" id="keywords" name="keywords" required placeholder="Византия, Константинополь, Царьград">

    <label for="annual_visitors">Годовая посещаемость</label>
    <input type="number" id="annual_visitors" name="annual_visitors" placeholder="10000">

    <label for="manual_urls">Ссылки для обязательной проверки (по одной на строку)</label>
    <textarea id="manual_urls" name="manual_urls" placeholder="https://example.com/post1"></textarea>

    <button type="submit">Запустить анализ</button>
</form>

<div id="progress" style="display:none;">
    <h2>Анализ выполняется...</h2>
    <div id="progress-status"></div>
    <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
    <div id="progress-text"></div>
</div>

<script>
document.getElementById('search-form').onsubmit = async function(e) {
    e.preventDefault();
    const form = e.target;
    const data = {
        object_name: form.object_name.value,
        keywords: form.keywords.value,
        annual_visitors: form.annual_visitors.value ? parseInt(form.annual_visitors.value) : null,
        manual_urls: form.manual_urls.value || null,
    };

    const resp = await fetch('/api/search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
    });
    const result = await resp.json();

    document.getElementById('search-form').style.display = 'none';
    document.getElementById('progress').style.display = 'block';

    const evtSource = new EventSource(`/api/tasks/${result.task_id}/progress`);
    evtSource.addEventListener('progress', function(event) {
        const data = JSON.parse(event.data);
        const pct = data.total > 0 ? Math.round(data.processed / data.total * 100) : 0;
        document.getElementById('progress-fill').style.width = pct + '%';
        document.getElementById('progress-status').innerHTML =
            `Обработано: ${data.processed} из ${data.total} | Найдено с ключевым словом: ${data.found_keyword}`;
        document.getElementById('progress-text').innerHTML =
            data.current_url ? `Текущий: <a href="${data.current_url}" target="_blank">${data.current_title || data.current_url}</a>` : '';
    });
    evtSource.addEventListener('done', function(event) {
        evtSource.close();
        window.location.href = JSON.parse(event.data).redirect;
    });
    evtSource.addEventListener('error', function(event) {
        evtSource.close();
        document.getElementById('progress-text').innerHTML = '<div class="error">Ошибка при выполнении анализа</div>';
    });
};
</script>
{% endblock %}
```

- [ ] **Step 3: Create results.html**

```html
{% extends "base.html" %}
{% block title %}Результаты анализа{% endblock %}
{% block content %}

{% if error %}
<div class="error">{{ error }}</div>
<a href="/">Вернуться к форме</a>
{% elif report %}
<h1>Результаты анализа</h1>

<p><strong>Объект:</strong> {{ report.object_name }}</p>
<p><strong>Ключевые слова:</strong> {{ report.keywords }}</p>

<div>
    <div class="stat">
        <div class="stat-value">{{ report.total_mentions }}</div>
        <div class="stat-label">Всего найдено</div>
    </div>
    <div class="stat">
        <div class="stat-value">{{ report.mentions_with_keyword }}</div>
        <div class="stat-label">С ключевым словом</div>
    </div>
    <div class="stat">
        <div class="stat-value">{{ report.keyword_percentage }}%</div>
        <div class="stat-label">% с ключевым словом</div>
    </div>
    {% if report.percentage_of_visitors is not none %}
    <div class="stat">
        <div class="stat-value">{{ report.percentage_of_visitors }}%</div>
        <div class="stat-label">% от посетителей ({{ report.annual_visitors }}/год)</div>
    </div>
    {% endif %}
</div>

{% if report.results %}
<table>
    <thead>
        <tr>
            <th>#</th>
            <th>URL</th>
            <th>Заголовок</th>
            <th>Ключевое слово</th>
            <th>Дата</th>
            <th>Геопривязка</th>
            <th>Релев.</th>
        </tr>
    </thead>
    <tbody>
        {% for r in report.results %}
        <tr>
            <td>{{ loop.index }}</td>
            <td><a href="{{ r.url }}" target="_blank">{{ r.url[:50] }}...</a></td>
            <td>{{ r.title or '—' }}</td>
            <td>{{ r.keyword_found or '—' }}</td>
            <td>{{ r.publication_date or r.date_mentioned or '—' }}</td>
            <td>{{ r.author_location or '—' }}</td>
            <td>{{ r.relevance_score }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>Результаты не найдены.</p>
{% endif %}

<a href="/">Новый анализ</a>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Verify templates render**

Run: `cd cultural-history-app && python -c "from app.main import app; print('Templates loaded OK')"`
Expected: Templates loaded OK

---

### Task 8: SearXNG deployment config

**Files:**
- Create: `cultural-history-app/searxng/settings.yml`
- Create: `cultural-history-app/docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

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

volumes:
  searxng-data:
```

- [ ] **Step 2: Create searxng/settings.yml**

```yaml
use_default_settings: true

server:
  secret_key: "change-me-to-a-random-string"
  bind_address: "0.0.0.0"
  port: 8080

search:
  safe_search: 0
  autocomplete: ""
  formats:
    - html
    - json

engines:
  - name: google
    engine: google
    shortcut: g

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg

  # Yandex requires API keys from https://xml.yandex.ru
  # - name: yandex
  #   engine: yandex
  #   use_xpath: true
  #   shortcut: ya

outgoing:
  request_timeout: 10.0
  max_request_timeout: 20.0
  useragent_suffix: ""
  # If behind a proxy, uncomment:
  # proxies:
  #   all://:
  #     - socks5h://proxy:1080
```

---

### Task 9: Integration test — full flow

**Files:**
- Create: `cultural-history-app/tests/test_integration.py`

- [ ] **Step 1: Create integration test**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import init_db, engine


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: c.execute("DELETE FROM results"))
        await conn.run_sync(lambda c: c.execute("DELETE FROM tasks"))
        await conn.run_sync(lambda c: c.execute("DELETE FROM url_cache"))


@pytest.mark.asyncio
async def test_full_api_flow(setup_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create search task
        resp = await client.post("/api/search", json={
            "object_name": "Test Monastery",
            "keywords": "test_kw",
            "annual_visitors": 1000,
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Check progress endpoint exists
        resp = await client.get(f"/api/tasks/{task_id}/progress")
        assert resp.status_code == 200

        # Check results page renders (task may still be processing)
        resp = await client.get(f"/results/{task_id}")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests**

Run: `cd cultural-history-app && python -m pytest tests/ -v`
Expected: All tests pass

---

### Task 10: Create data directory and test run

- [ ] **Step 1: Create data directory**

Run: `cd cultural-history-app && New-Item -ItemType Directory -Path data -Force`

- [ ] **Step 2: Verify server starts**

Run: `cd cultural-history-app && uvicorn app.main:app --host 0.0.0.0 --port 8000`
Expected: Server starts, visit http://localhost:8000 to see the form.

- [ ] **Step 3: Initialize git**

```bash
cd G:/_ИИ Византия
git init
git add cultural-history-app/ docs/ AGENTS.md "Тревел блоги.docx"
git commit -m "feat: initial project scaffold with web service"
```
