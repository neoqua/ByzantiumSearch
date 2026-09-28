import asyncio
import json
import logging
from typing import Dict, Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import async_session
from app.models import Task, Result, UrlCache, utcnow
from app.search import search_urls_detailed
from app.scraper import fetch_and_analyze, make_http_client, _blank_analysis
from app.schemas import LLMSettings

logger = logging.getLogger(__name__)

_PROGRESS_KEYS = (
    "status", "processed", "total", "found_keyword", "current_url", "current_title",
)
_ACTIVE_STATUSES = ("pending", "processing", "queued")

# One analysis at a time in this process
_analysis_slot = asyncio.Semaphore(1)

# In-memory progress store: task_id -> dict (fast path while the process lives)
_progress_store: Dict[str, Dict[str, Any]] = {}


def get_progress(task_id: str) -> Optional[Dict[str, Any]]:
    return _progress_store.get(task_id)


def seed_progress(task_id: str) -> Dict[str, Any]:
    entry = {
        "status": "pending",
        "processed": 0,
        "total": 0,
        "found_keyword": 0,
        "current_url": None,
        "current_title": None,
    }
    _progress_store[task_id] = entry
    return entry


def public_progress(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: entry.get(k) for k in _PROGRESS_KEYS}


def progress_from_task(task: Task) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if task.progress_json:
        try:
            parsed = json.loads(task.progress_json)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    out = {
        "status": task.status,
        "processed": data.get("processed", 0) or 0,
        "total": data.get("total", 0) or 0,
        "found_keyword": data.get("found_keyword", 0) or 0,
        "current_url": data.get("current_url"),
        "current_title": data.get("current_title"),
        "error_message": task.error_message,
    }
    return out


def forget_progress(task_id: str) -> None:
    _progress_store.pop(task_id, None)


def _split_keywords(keywords_raw: str):
    return [kw.strip() for kw in keywords_raw.split(",") if kw.strip()]


def _split_urls(urls_raw: Optional[str]):
    if not urls_raw:
        return []
    return [u.strip() for u in urls_raw.split("\n") if u.strip()]


def _cache_keywords(keywords):
    return ",".join(keywords) + "#kwv3"


def _dump_progress(entry: Dict[str, Any]) -> str:
    return json.dumps(public_progress(entry), ensure_ascii=False)


def _wants_stop(task_id: str, entry: Dict[str, Any]) -> bool:
    return bool(
        entry.get("stop_requested")
        or (_progress_store.get(task_id) or {}).get("stop_requested")
    )


async def fail_interrupted_tasks() -> int:
    """Mark unfinished tasks as failed — they cannot survive a process restart."""
    async with async_session() as session:
        stmt = select(Task).where(Task.status.in_(_ACTIVE_STATUSES))
        tasks = (await session.execute(stmt)).scalars().all()
        if not tasks:
            return 0
        now = utcnow()
        for task in tasks:
            task.status = "failed"
            task.error_message = "прервано перезапуском"
            task.completed_at = now
            entry = progress_from_task(task)
            entry["status"] = "failed"
            task.progress_json = json.dumps(
                {k: entry.get(k) for k in _PROGRESS_KEYS}, ensure_ascii=False
            )
        await session.commit()
        return len(tasks)


async def request_stop(task_id: str) -> bool:
    found_live = False
    progress = _progress_store.get(task_id)
    if progress is not None:
        progress["stop_requested"] = True
        found_live = True
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return False
        if task.status in _ACTIVE_STATUSES:
            task.stop_requested = True
            await session.commit()
            return True
        return found_live


async def _mark_task_failed(task_id: str, error_message: Optional[str] = None):
    try:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = "failed"
                task.completed_at = utcnow()
                if error_message:
                    task.error_message = error_message
                entry = _progress_store.get(task_id) or progress_from_task(task)
                entry["status"] = "failed"
                task.progress_json = _dump_progress(entry)
                await session.commit()
    except Exception as e:
        logger.error("Failed to mark task %s as failed: %s", task_id, e)
    forget_progress(task_id)


async def _persist_engine_used(task_id: str, engine_used: str):
    try:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.search_engine_used = engine_used
                await session.commit()
    except Exception as e:
        logger.error("Failed to store search_engine_used for %s: %s", task_id, e)


async def _mark_queued(task_id: str, entry: Dict[str, Any]) -> None:
    entry["status"] = "queued"
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            task.status = "queued"
            task.progress_json = _dump_progress(entry)
            await session.commit()


async def _finalize_stopped(task_id: str, entry: Dict[str, Any]) -> None:
    entry["status"] = "stopped"
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            task.status = "stopped"
            task.completed_at = utcnow()
            task.progress_json = _dump_progress(entry)
            await session.commit()
    forget_progress(task_id)


async def _write_cache_and_result(
    session,
    task: Optional[Task],
    task_id: str,
    url: str,
    title: str,
    object_name: str,
    cache_keywords: str,
    llm_data: dict,
    entry: Dict[str, Any],
    counters: Dict[str, int],
    write_cache: bool,
) -> None:
    analysis_status = llm_data.get("analysis_status") or "ok"
    if write_cache and analysis_status == "ok":
        payload = json.dumps(llm_data, ensure_ascii=False)
        cached = await session.get(UrlCache, url)
        if cached:
            cached.object_name = object_name
            cached.keywords = cache_keywords
            cached.result_json = payload
            cached.raw_text_hash = llm_data.get("raw_text_hash")
        else:
            session.add(UrlCache(
                url=url,
                object_name=object_name,
                keywords=cache_keywords,
                result_json=payload,
                raw_text_hash=llm_data.get("raw_text_hash"),
            ))
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                task = await session.get(Task, task_id)
                existing = await session.get(UrlCache, url)
                if existing:
                    existing.object_name = object_name
                    existing.keywords = cache_keywords
                    existing.result_json = payload
                    existing.raw_text_hash = llm_data.get("raw_text_hash")

    mentions = llm_data.get("mentions_object", False)
    has_kw = llm_data.get("has_keyword", False)
    if has_kw and analysis_status == "ok":
        counters["found_keyword"] += 1

    session.add(Result(
        task_id=task_id,
        url=url,
        title=title,
        mentions_object=mentions if analysis_status == "ok" else False,
        has_keyword=has_kw if analysis_status != "fetch_failed" else False,
        keyword_found=llm_data.get("keyword_found"),
        date_mentioned=llm_data.get("date_mentioned"),
        publication_date=llm_data.get("publication_date"),
        author_location=llm_data.get("author_location"),
        relevance_score=llm_data.get("relevance_score", 0.0),
        raw_text_hash=llm_data.get("raw_text_hash"),
        source_type=llm_data.get("source_type", "other"),
        analysis_status=analysis_status,
    ))
    counters["processed"] += 1
    entry.update(
        processed=counters["processed"],
        found_keyword=counters["found_keyword"],
        current_url=url,
        current_title=title,
    )
    if task:
        task.progress_json = _dump_progress(entry)
    await session.commit()


async def _execute_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str],
    llm_settings: Optional[LLMSettings],
    search_engine: str,
    entry: Dict[str, Any],
):
    keywords = _split_keywords(keywords_raw)
    manual_urls = _split_urls(manual_urls_raw)

    entry.update(
        status="processing",
        processed=0,
        total=0,
        found_keyword=0,
        current_url=None,
        current_title=None,
    )

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            forget_progress(task_id)
            return
        task.status = "processing"
        task.error_message = None
        task.stop_requested = False
        task.progress_json = _dump_progress(entry)
        await session.commit()

    all_urls = []
    engine_used = search_engine
    search_error = None
    try:
        search_results, engine_used, _fallback = await search_urls_detailed(
            object_name, keywords, engine=search_engine
        )
        all_urls.extend(search_results)
    except Exception as e:
        logger.error("Search failed: %s", e)
        search_error = str(e)

    await _persist_engine_used(task_id, engine_used)

    for url in manual_urls:
        if not any(item["url"] == url for item in all_urls):
            all_urls.append({"url": url, "title": ""})

    if not all_urls:
        if search_error:
            msg = (
                f"Поиск недоступен ({search_error}). "
                "Ручных ссылок нет."
            )
        else:
            msg = (
                "Поиск не вернул ни одного URL, и список ручных ссылок пуст."
            )
        if task_id in _progress_store:
            _progress_store[task_id]["status"] = "failed"
        await _mark_task_failed(task_id, msg)
        return

    entry["total"] = len(all_urls)
    cache_keywords = _cache_keywords(keywords)
    counters = {"processed": 0, "found_keyword": 0}
    write_lock = asyncio.Lock()
    fetch_sem = asyncio.Semaphore(settings.fetch_concurrency)

    async def handle(item: dict, client: httpx.AsyncClient) -> None:
        url = item["url"]
        title = item["title"]
        try:
            if _wants_stop(task_id, entry):
                return
            from_cache = False
            llm_data = None
            async with write_lock:
                async with async_session() as session:
                    cached = await session.get(UrlCache, url)
                    if (
                        cached
                        and cached.object_name == object_name
                        and cached.keywords == cache_keywords
                    ):
                        llm_data = json.loads(cached.result_json) if cached.result_json else {}
                        llm_data.setdefault("analysis_status", "ok")
                        from_cache = True
                        task = await session.get(Task, task_id)
                        await _write_cache_and_result(
                            session, task, task_id, url, title, object_name,
                            cache_keywords, llm_data, entry, counters,
                            write_cache=False,
                        )
            if from_cache:
                return
            if _wants_stop(task_id, entry):
                return
            async with fetch_sem:
                if _wants_stop(task_id, entry):
                    return
                entry.update(current_url=url, current_title=title)
                llm_data = await fetch_and_analyze(
                    url, object_name, keywords, title,
                    llm_settings=llm_settings, client=client,
                )
            async with write_lock:
                async with async_session() as session:
                    task = await session.get(Task, task_id)
                    await _write_cache_and_result(
                        session, task, task_id, url, title, object_name,
                        cache_keywords, llm_data, entry, counters,
                        write_cache=True,
                    )
        except Exception:
            logger.exception("Failed processing %s", url)
            async with write_lock:
                async with async_session() as session:
                    task = await session.get(Task, task_id)
                    await _write_cache_and_result(
                        session, task, task_id, url, title, object_name,
                        cache_keywords, _blank_analysis(url, title, "fetch_failed"),
                        entry, counters, write_cache=False,
                    )

    client = make_http_client()
    try:
        await asyncio.gather(
            *[handle(item, client) for item in all_urls],
            return_exceptions=True,
        )
    finally:
        await client.aclose()

    stopped = _wants_stop(task_id, entry)
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task and task.stop_requested:
            stopped = True
        final_status = "stopped" if stopped else "completed"
        if task:
            task.status = final_status
            task.completed_at = utcnow()
            entry["status"] = final_status
            task.progress_json = _dump_progress(entry)
            await session.commit()
    forget_progress(task_id)


async def run_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str] = None,
    llm_settings: Optional[LLMSettings] = None,
    search_engine: str = "searxng",
):
    entry = _progress_store.get(task_id) or seed_progress(task_id)
    acquired = False
    try:
        if _analysis_slot.locked():
            await _mark_queued(task_id, entry)
        await _analysis_slot.acquire()
        acquired = True

        if _wants_stop(task_id, entry):
            await _finalize_stopped(task_id, entry)
            return
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task and task.stop_requested:
                await _finalize_stopped(task_id, entry)
                return

        await _execute_analysis(
            task_id, object_name, keywords_raw, manual_urls_raw,
            llm_settings, search_engine, entry,
        )
    except Exception as e:
        logger.exception("Analysis failed for task %s: %s", task_id, e)
        if task_id in _progress_store:
            _progress_store[task_id]["status"] = "failed"
        await _mark_task_failed(task_id, str(e))
    finally:
        if acquired:
            _analysis_slot.release()
