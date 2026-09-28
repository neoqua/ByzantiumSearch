import os
import tempfile
import uuid
import asyncio

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

    async def fake_fetch(url, object_name, keywords, title, llm_settings=None, client=None):
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

    async def fail_fetch(url, object_name, keywords, title, llm_settings=None, client=None):
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
    async def no_text(url, client=None):
        return None

    monkeypatch.setattr("app.scraper.fetch_page_text", no_text)
    result = await fetch_and_analyze("https://x", "Obj", ["Византия"], "t")
    assert result["analysis_status"] == "fetch_failed"
    assert result["mentions_object"] is False


@pytest.mark.asyncio
async def test_fetch_and_analyze_llm_failed_still_matches_keywords(monkeypatch):
    async def page(url, client=None):
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


@pytest.mark.asyncio
async def test_fail_interrupted_tasks_marks_pending_and_processing():
    await init_db()
    async with async_session() as s:
        pending = Task(object_name="A", keywords="k", search_engine="openserp", status="pending")
        running = Task(object_name="B", keywords="k", search_engine="openserp", status="processing")
        queued = Task(object_name="D", keywords="k", search_engine="openserp", status="queued")
        done = Task(object_name="C", keywords="k", search_engine="openserp", status="completed")
        s.add_all([pending, running, queued, done])
        await s.commit()
        ids = (pending.id, running.id, queued.id, done.id)

    from app.analyzer import fail_interrupted_tasks, get_progress
    n = await fail_interrupted_tasks()
    assert n >= 3

    async with async_session() as s:
        a = await s.get(Task, ids[0])
        b = await s.get(Task, ids[1])
        q = await s.get(Task, ids[2])
        c = await s.get(Task, ids[3])
        assert a.status == "failed"
        assert b.status == "failed"
        assert q.status == "failed"
        assert "перезапуском" in (a.error_message or "")
        assert c.status == "completed"
        assert get_progress(ids[0]) is None


@pytest.mark.asyncio
async def test_progress_json_persisted_and_store_cleared(monkeypatch):
    await init_db()

    async def one_url(*args, **kwargs):
        return [{"url": "https://ok.example/x", "title": "X"}], "openserp", False

    async def ok_fetch(url, object_name, keywords, title, llm_settings=None, client=None):
        return {
            "url": url, "title": title, "mentions_object": True, "has_keyword": True,
            "keyword_found": "kw", "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "blog", "relevance_score": 0.5,
            "raw_text_hash": "h", "analysis_status": "ok",
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", one_url)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", ok_fetch)

    from app.analyzer import get_progress
    import json as json_mod

    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")

    assert get_progress(task_id) is None
    async with async_session() as s:
        task = await s.get(Task, task_id)
        assert task.status == "completed"
        data = json_mod.loads(task.progress_json)
        assert data["processed"] == 1
        assert data["total"] == 1
        assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_source_mix_stored_on_task(monkeypatch):
    await init_db()

    async def mixed(*args, **kwargs):
        return (
            [
                {"url": "https://www.tourister.ru/a", "title": "Заметка"},
                {"url": "https://agency.example/", "title": "Турагентство"},
            ],
            "openserp",
            False,
        )

    async def ok_fetch(url, object_name, keywords, title, llm_settings=None, client=None):
        return {
            "url": url, "title": title, "mentions_object": False, "has_keyword": False,
            "keyword_found": None, "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "other", "relevance_score": 0.0,
            "raw_text_hash": "h", "analysis_status": "ok",
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", mixed)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", ok_fetch)

    import json as json_mod

    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")

    async with async_session() as s:
        task = await s.get(Task, task_id)
        mix = json_mod.loads(task.progress_json)["source_mix"]
        assert mix["ugc"] == 1
        assert mix["agency"] == 1
        assert mix["travel_blog"] == 1


@pytest.mark.asyncio
async def test_second_analysis_is_queued_while_first_runs(monkeypatch):
    await init_db()
    gate = asyncio.Event()

    async def blocking_search(*args, **kwargs):
        await gate.wait()
        return [], "openserp", False

    monkeypatch.setattr("app.analyzer.search_urls_detailed", blocking_search)

    async with async_session() as s:
        t1 = Task(object_name="A", keywords="k", search_engine="openserp", status="pending")
        t2 = Task(object_name="B", keywords="k", search_engine="openserp", status="pending")
        s.add_all([t1, t2])
        await s.commit()
        id1, id2 = t1.id, t2.id

    f1 = asyncio.create_task(run_analysis(id1, "A", "k", None, None, "openserp"))
    for _ in range(50):
        await asyncio.sleep(0.02)
        async with async_session() as s:
            first = await s.get(Task, id1)
            if first.status == "processing":
                break
    else:
        gate.set()
        await f1
        raise AssertionError("first analysis did not enter processing")

    f2 = asyncio.create_task(run_analysis(id2, "B", "k", None, None, "openserp"))
    for _ in range(50):
        await asyncio.sleep(0.02)
        async with async_session() as s:
            second = await s.get(Task, id2)
            if second.status == "queued":
                break
    else:
        gate.set()
        await asyncio.gather(f1, f2)
        raise AssertionError("second analysis was not queued")

    gate.set()
    await f1
    await f2

    async with async_session() as s:
        first = await s.get(Task, id1)
        second = await s.get(Task, id2)
        assert first.status == "failed"
        assert second.status == "failed"


@pytest.mark.asyncio
async def test_url_fetch_concurrency_is_capped(monkeypatch):
    await init_db()
    current = 0
    peak = 0
    lock = asyncio.Lock()
    prefix = f"https://ex.example/{uuid.uuid4().hex}/"

    async def five_urls(*args, **kwargs):
        return (
            [{"url": f"{prefix}{i}", "title": str(i)} for i in range(5)],
            "openserp",
            False,
        )

    async def slow_fetch(url, object_name, keywords, title, llm_settings=None, client=None):
        nonlocal current, peak
        async with lock:
            current += 1
            peak = max(peak, current)
        await asyncio.sleep(0.05)
        async with lock:
            current -= 1
        return {
            "url": url, "title": title, "mentions_object": False, "has_keyword": False,
            "keyword_found": None, "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "other", "relevance_score": 0.0,
            "raw_text_hash": "h", "analysis_status": "ok",
        }

    from app.config import settings as app_settings
    monkeypatch.setattr("app.analyzer.search_urls_detailed", five_urls)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", slow_fetch)
    monkeypatch.setattr(app_settings, "fetch_concurrency", 2)

    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")
    assert 1 <= peak <= 2
    async with async_session() as s:
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert len(rows) == 5

