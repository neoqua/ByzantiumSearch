import json
import os
import tempfile
import uuid
import asyncio

_test_db_path = os.path.join(tempfile.gettempdir(), f"test_analyzer_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

import pytest
from sqlalchemy import select

from app.database import init_db, async_session
from app.models import Task, Result, UrlCacheV2
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

    async def fake_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
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

    async def fail_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
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
        cached = await s.get(
            UrlCacheV2, ("https://down.example/x", "Obj", _cache_keywords(["kw"]))
        )
        assert cached is None


@pytest.mark.asyncio
async def test_fetch_and_analyze_fetch_failed(monkeypatch):
    async def no_bytes(url, client=None):
        return None

    monkeypatch.setattr("app.scraper.fetch_page_bytes", no_bytes)
    result = (await fetch_and_analyze("https://x", "Obj", ["Византия"], "t"))[0]
    assert result["analysis_status"] == "fetch_failed"
    assert result["mentions_object"] is False


@pytest.mark.asyncio
async def test_fetch_and_analyze_llm_failed_still_matches_keywords(monkeypatch):
    async def page(url, client=None):
        return "<p>Текст про Византию на странице</p>".encode("utf-8")

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

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm_fail)
    result = (await fetch_and_analyze("https://x", "Obj", ["Византия"], "t"))[0]
    assert result["analysis_status"] == "llm_failed"
    assert result["has_keyword"] is True
    assert "византию" in (result["keyword_found"] or "")


@pytest.mark.asyncio
async def test_fetch_and_analyze_prefers_page_date_over_llm(monkeypatch):
    html = (
        '<html><head><meta property="article:published_time" '
        'content="2021-03-15T00:00:00Z"></head>'
        "<body><p>Текст про Византию</p></body></html>"
    ).encode("utf-8")

    async def page(url, client=None):
        return html

    async def llm_ok(*args, **kwargs):
        return {
            "mentions_object": True,
            "publication_date": "01.01.1999",
            "date_mentioned": None,
            "author_location": None,
            "relevance_score": 0.5,
            "source_type": "blog",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm_ok)
    result = (await fetch_and_analyze("https://x", "Obj", ["Византия"], "t"))[0]
    assert result["publication_date"] == "15.03.2021"
    assert result["date_source"] == "page"


def test_cache_key_bumped_for_status_change():
    assert _cache_keywords(["a", "b"]).endswith("#kwv7")
    assert "#kwv6" not in _cache_keywords(["a"])


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

    async def ok_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
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

    async def ok_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
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

    async def slow_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
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


@pytest.mark.asyncio
async def test_cache_not_shared_across_objects(monkeypatch):
    await init_db()
    calls = []

    async def one_url(*args, **kwargs):
        return [{"url": "https://shared.example/post", "title": "X"}], "openserp", False

    async def tracking_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
        calls.append(object_name)
        return {
            "url": url, "title": title, "mentions_object": True, "has_keyword": False,
            "keyword_found": None, "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "blog", "relevance_score": 0.5,
            "raw_text_hash": "h", "analysis_status": "ok", "date_source": None,
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", one_url)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", tracking_fetch)

    ids = []
    async with async_session() as s:
        for name in ("Монастырь А", "Монастырь Б"):
            task = Task(object_name=name, keywords="kw", search_engine="openserp", status="pending")
            s.add(task)
            await s.commit()
            ids.append((task.id, name))

    for task_id, name in ids:
        await run_analysis(task_id, name, "kw", None, None, "openserp")

    assert calls == ["Монастырь А", "Монастырь Б"]
    async with async_session() as s:
        a = await s.get(UrlCacheV2, ("https://shared.example/post", "Монастырь А", _cache_keywords(["kw"])))
        b = await s.get(UrlCacheV2, ("https://shared.example/post", "Монастырь Б", _cache_keywords(["kw"])))
        assert a is not None and b is not None
        assert a.result_json != "" or b.result_json != ""


@pytest.mark.asyncio
async def test_search_phase_is_written_to_progress(monkeypatch):
    import json as json_mod
    await init_db()
    captured = {}

    async def search_with_progress(*args, **kwargs):
        cb = kwargs.get("on_progress")
        assert cb is not None
        await cb({
            "engine": "openserp",
            "query": "Obj отзывы",
            "index": 2,
            "total": 7,
            "urls_found": 4,
        })
        from app.analyzer import get_progress
        captured["live"] = dict(get_progress(task_id) or {})
        async with async_session() as s:
            row = await s.get(Task, task_id)
            captured["db"] = json_mod.loads(row.progress_json)
        return (
            [{"url": "https://ok.example/x", "title": "X", "source_type": "ugc", "travel_blog": False}],
            "openserp",
            False,
        )

    async def fake_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
        return {
            "url": url, "title": title, "mentions_object": True, "has_keyword": True,
            "keyword_found": "kw", "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "blog", "relevance_score": 0.9,
            "raw_text_hash": "h", "analysis_status": "ok", "date_source": None,
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", search_with_progress)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fake_fetch)

    async with async_session() as s:
        task = Task(object_name="Obj", keywords="kw", search_engine="openserp", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", None, None, "openserp")

    assert captured["live"]["phase"] == "search"
    assert captured["live"]["search_query"] == "Obj отзывы"
    assert captured["live"]["search_query_index"] == 2
    assert captured["live"]["search_query_total"] == 7
    assert captured["live"]["urls_found"] == 4
    assert captured["db"]["phase"] == "search"
    assert captured["db"]["search_backend"] == "openserp"


@pytest.mark.asyncio
async def test_run_analysis_one_result_per_review(monkeypatch):
    await init_db()

    async def boom(*args, **kwargs):
        raise AssertionError("search should not run")

    async def fake_fetch(url, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
        return [
            {
                "url": url,
                "title": "Отзыв 1",
                "mentions_object": True,
                "has_keyword": True,
                "keyword_found": "Византия",
                "date_mentioned": None,
                "publication_date": "01.06.2024",
                "author_location": None,
                "source_type": "ugc",
                "content_kind": "personal_review",
                "excerpt": "Пещеры произвели сильное впечатление",
                "impression": "Понравились пещеры",
                "relevance_score": 1.0,
                "raw_text_hash": "h1",
                "analysis_status": "ok",
                "date_source": "page",
            },
            {
                "url": url,
                "title": "Отзыв 2",
                "mentions_object": True,
                "has_keyword": False,
                "keyword_found": None,
                "date_mentioned": None,
                "publication_date": "10.01.2023",
                "author_location": None,
                "source_type": "ugc",
                "content_kind": "personal_review",
                "excerpt": "Фрески стоит увидеть",
                "impression": "Хвалит фрески",
                "relevance_score": 0.7,
                "raw_text_hash": "h2",
                "analysis_status": "ok",
                "date_source": "page",
            },
        ]

    monkeypatch.setattr("app.analyzer.search_urls_detailed", boom)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fake_fetch)

    async with async_session() as s:
        task = Task(
            object_name="Obj", keywords="kw", search_engine="openserp",
            status="pending", manual_urls="https://otzyv.example/list",
            content_scope="all",
        )
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", "https://otzyv.example/list", None, "openserp")

    async with async_session() as s:
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert len(rows) == 2
        assert {r.excerpt for r in rows} == {
            "Пещеры произвели сильное впечатление",
            "Фрески стоит увидеть",
        }
        cached = await s.get(
            UrlCacheV2, ("https://otzyv.example/list", "Obj", _cache_keywords(["kw"]))
        )
        assert cached is not None
        payload = json.loads(cached.result_json)
        assert isinstance(payload, list)
        assert len(payload) == 2


def test_mixed_llm_failed_page_is_not_cacheable():
    from app.analyzer import _should_cache_units
    assert _should_cache_units([
        {"analysis_status": "ok"},
        {"analysis_status": "llm_failed"},
    ]) is False
    assert _should_cache_units([
        {"analysis_status": "ok"},
        {"analysis_status": "prefiltered"},
    ]) is True
    assert _should_cache_units([]) is False


@pytest.mark.asyncio
async def test_mixed_llm_failed_cache_is_ignored(monkeypatch):
    await init_db()
    url = "https://maps.example/reviews"
    key = _cache_keywords(["kw"])
    called = {"n": 0}

    async def boom(*args, **kwargs):
        raise AssertionError("search should not run")

    async def fake_fetch(u, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
        called["n"] += 1
        return [
            {
                "url": u, "title": "r1", "mentions_object": True, "has_keyword": False,
                "keyword_found": None, "date_mentioned": None, "publication_date": None,
                "author_location": None, "source_type": "ugc",
                "content_kind": "personal_review", "excerpt": "цитата",
                "impression": "смысл", "relevance_score": 0.7, "raw_text_hash": "h1",
                "analysis_status": "ok",
            },
            {
                "url": u, "title": "r2", "mentions_object": True, "has_keyword": False,
                "keyword_found": None, "date_mentioned": None, "publication_date": None,
                "author_location": None, "source_type": "ugc",
                "content_kind": "personal_review", "excerpt": "ещё",
                "impression": "ещё смысл", "relevance_score": 0.7, "raw_text_hash": "h2",
                "analysis_status": "ok",
            },
        ]

    monkeypatch.setattr("app.analyzer.search_urls_detailed", boom)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fake_fetch)

    async with async_session() as s:
        s.add(UrlCacheV2(
            url=url, object_name="Obj", keywords=key,
            result_json=json.dumps([
                {"analysis_status": "ok", "title": "old"},
                {"analysis_status": "llm_failed", "title": "bad"},
            ], ensure_ascii=False),
            raw_text_hash="old",
        ))
        task = Task(
            object_name="Obj", keywords="kw", search_engine="openserp",
            status="pending", manual_urls=url, content_scope="all",
        )
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", url, None, "openserp")
    assert called["n"] == 1
    async with async_session() as s:
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert len(rows) == 2
        assert all(r.analysis_status == "ok" for r in rows)
        cached = await s.get(UrlCacheV2, (url, "Obj", key))
        assert cached is not None
        payload = json.loads(cached.result_json)
        assert all((u.get("analysis_status") or "ok") == "ok" for u in payload)


@pytest.mark.asyncio
async def test_use_cache_false_skips_good_cache(monkeypatch):
    await init_db()
    url = "https://cached.example/post"
    key = _cache_keywords(["kw"])
    called = {"n": 0}

    async def boom(*args, **kwargs):
        raise AssertionError("search should not run")

    async def fake_fetch(u, object_name, keywords, title, llm_settings=None, client=None, **kwargs):
        called["n"] += 1
        return {
            "url": u, "title": "fresh", "mentions_object": True, "has_keyword": False,
            "keyword_found": None, "date_mentioned": None, "publication_date": None,
            "author_location": None, "source_type": "ugc",
            "content_kind": "personal_review", "excerpt": "новая цитата",
            "impression": "новый смысл", "relevance_score": 0.7, "raw_text_hash": "h2",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.analyzer.search_urls_detailed", boom)
    monkeypatch.setattr("app.analyzer.fetch_and_analyze", fake_fetch)

    async with async_session() as s:
        s.add(UrlCacheV2(
            url=url, object_name="Obj", keywords=key,
            result_json=json.dumps({
                "analysis_status": "ok", "title": "from cache", "excerpt": "старая",
            }, ensure_ascii=False),
            raw_text_hash="old",
        ))
        task = Task(
            object_name="Obj", keywords="kw", search_engine="openserp",
            status="pending", manual_urls=url, content_scope="all", use_cache=False,
        )
        s.add(task)
        await s.commit()
        task_id = task.id

    await run_analysis(task_id, "Obj", "kw", url, None, "openserp")
    assert called["n"] == 1
    async with async_session() as s:
        rows = (await s.execute(select(Result).where(Result.task_id == task_id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].excerpt == "новая цитата"


