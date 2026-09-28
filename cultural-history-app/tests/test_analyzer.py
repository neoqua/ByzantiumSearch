import os
import tempfile
import uuid

_test_db_path = os.path.join(tempfile.gettempdir(), f"test_analyzer_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

import pytest
from sqlalchemy import select

from app.database import init_db, async_session
from app.models import Task, Result, UrlCache
from app.analyzer import run_analysis, _cache_keywords
from app.scraper import fetch_and_analyze


@pytest.mark.asyncio
async def test_empty_search_without_manual_urls_fails(monkeypatch):
    await init_db()

    async def empty(*args, **kwargs):
        return [], "openserp", False

    monkeypatch.setattr("app.analyzer.search_urls_detailed", empty)
    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")

    async with async_session() as s:
        task = await s.get(Task, task_id)
        assert task.status == "failed"
        assert "не вернул" in (task.error_message or "")
        assert task.search_engine_used == "openserp"
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_search_error_with_manual_url_continues(monkeypatch):
    await init_db()

    async def boom(*args, **kwargs):
        raise RuntimeError("engine down")

    async def fake_fetch(url, object_name, keywords, title, llm_settings=None):
        return {
            "url": url,
            "title": title,
            "mentions_object": True,
            "has_keyword": True,
            "keyword_found": "kw",
            "date_mentioned": None,
            "publication_date": None,
            "author_location": None,
            "source_type": "blog",
            "relevance_score": 0.9,
            "raw_text_hash": "abc",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", boom)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fake_fetch)

    async with async_session() as s:
        task = Task(
            object_name="Obj", keywords="kw", search_engine="openserp",
            status="pending", manual_urls="https://example.com/post",
        )
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", "https://example.com/post", None, "openserp")

    async with async_session() as s:
        task = await s.get(Task, task_id)
        assert task.status == "completed"
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].analysis_status == "ok"
        assert rows[0].mentions_object is True


@pytest.mark.asyncio
async def test_fetch_failed_not_cached(monkeypatch):
    await init_db()

    async def one_url(*args, **kwargs):
        return [{"url": "https://down.example/x", "title": "X"}], "openserp", False

    async def fail_fetch(url, object_name, keywords, title, llm_settings=None):
        return {
            "url": url,
            "title": title,
            "mentions_object": False,
            "has_keyword": False,
            "keyword_found": None,
            "date_mentioned": None,
            "publication_date": None,
            "author_location": None,
            "source_type": "other",
            "relevance_score": 0.0,
            "raw_text_hash": None,
            "analysis_status": "fetch_failed",
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", one_url)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fail_fetch)

    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")

    async with async_session() as s:
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert rows[0].analysis_status == "fetch_failed"
        assert rows[0].mentions_object is False
        cached = await s.get(UrlCache, "https://down.example/x")
        assert cached is None


@pytest.mark.asyncio
async def test_fetch_and_analyze_fetch_failed(monkeypatch):
    async def no_text(url):
        return None

    monkeypatch.setattr("app.scraper.fetch_page_text", no_text)
    result = await fetch_and_analyze("https://x", "Obj", ["Византия"], "t")
    assert result["analysis_status"] == "fetch_failed"
    assert result["mentions_object"] is False


@pytest.mark.asyncio
async def test_fetch_and_analyze_llm_failed_still_matches_keywords(monkeypatch):
    async def page(url):
        return "Текст про Византию на странице"

    async def llm_fail(*args, **kwargs):
        return {
            "mentions_object": False,
            "has_keyword": False,
            "keyword_found": None,
            "date_mentioned": None,
            "publication_date": None,
            "author_location": None,
            "relevance_score": 0.0,
            "source_type": "other",
            "analysis_status": "llm_failed",
        }

    monkeypatch.setattr("app.scraper.fetch_page_text", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm_fail)
    result = await fetch_and_analyze("https://x", "Obj", ["Византия"], "t")
    assert result["analysis_status"] == "llm_failed"
    assert result["has_keyword"] is True
    assert "византию" in (result["keyword_found"] or "")


def test_cache_key_bumped_for_status_change():
    assert _cache_keywords(["a", "b"]).endswith("#kwv3")
    assert "#kwv2" not in _cache_keywords(["a"])
