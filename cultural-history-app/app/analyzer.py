import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.exc import IntegrityError

from app.database import async_session
from app.models import Task, Result, UrlCache
from app.search import search_urls_detailed
from app.scraper import fetch_and_analyze
from app.schemas import LLMSettings

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


def _cache_keywords(keywords):
    return ",".join(keywords) + "#kwv3"


async def _mark_task_failed(task_id: str, error_message: Optional[str] = None):
    try:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = "failed"
                task.completed_at = datetime.utcnow()
                if error_message:
                    task.error_message = error_message
                await session.commit()
    except Exception as e:
        logger.error("Failed to mark task %s as failed: %s", task_id, e)


async def _persist_engine_used(task_id: str, engine_used: str):
    try:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.search_engine_used = engine_used
                await session.commit()
    except Exception as e:
        logger.error("Failed to store search_engine_used for %s: %s", task_id, e)


async def run_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str] = None,
    llm_settings: Optional[LLMSettings] = None,
    search_engine: str = "searxng",
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

    try:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if not task:
                return
            task.status = "processing"
            task.error_message = None
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
            await _mark_task_failed(task_id, msg)
            if task_id in _progress_store:
                _progress_store[task_id]["status"] = "failed"
            return

        total = len(all_urls)
        _progress_store[task_id]["total"] = total

        processed = 0
        found_keyword = 0
        cache_keywords = _cache_keywords(keywords)
        stopped = False

        async with async_session() as session:
            for entry in all_urls:
                if _progress_store[task_id].get("stop_requested"):
                    stopped = True
                    break

                url = entry["url"]
                title = entry["title"]

                _progress_store[task_id].update(
                    current_url=url,
                    current_title=title,
                )

                cached = await session.get(UrlCache, url)
                if (
                    cached
                    and cached.object_name == object_name
                    and cached.keywords == cache_keywords
                ):
                    llm_data = json.loads(cached.result_json) if cached.result_json else {}
                    llm_data.setdefault("analysis_status", "ok")
                else:
                    llm_data = await fetch_and_analyze(
                        url, object_name, keywords, title, llm_settings=llm_settings
                    )
                    status = llm_data.get("analysis_status") or "ok"
                    if status == "ok":
                        payload = json.dumps(llm_data, ensure_ascii=False)
                        if cached:
                            cached.object_name = object_name
                            cached.keywords = cache_keywords
                            cached.result_json = payload
                            cached.raw_text_hash = llm_data.get("raw_text_hash")
                            await session.commit()
                        else:
                            cache_entry = UrlCache(
                                url=url,
                                object_name=object_name,
                                keywords=cache_keywords,
                                result_json=payload,
                                raw_text_hash=llm_data.get("raw_text_hash"),
                            )
                            session.add(cache_entry)
                            try:
                                await session.commit()
                            except IntegrityError:
                                await session.rollback()
                                existing = await session.get(UrlCache, url)
                                if existing and existing.keywords == cache_keywords:
                                    llm_data = (
                                        json.loads(existing.result_json)
                                        if existing.result_json
                                        else llm_data
                                    )
                                    llm_data.setdefault("analysis_status", "ok")
                                elif existing:
                                    existing.object_name = object_name
                                    existing.keywords = cache_keywords
                                    existing.result_json = payload
                                    existing.raw_text_hash = llm_data.get("raw_text_hash")
                                    await session.commit()

                mentions = llm_data.get("mentions_object", False)
                has_kw = llm_data.get("has_keyword", False)
                analysis_status = llm_data.get("analysis_status") or "ok"

                if has_kw and analysis_status == "ok":
                    found_keyword += 1

                result_entry = Result(
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
                )
                session.add(result_entry)
                await session.commit()

                processed += 1
                _progress_store[task_id].update(
                    processed=processed,
                    found_keyword=found_keyword,
                )

            task = await session.get(Task, task_id)
            if task:
                task.status = "stopped" if stopped else "completed"
                task.completed_at = datetime.utcnow()
                await session.commit()

        _progress_store[task_id]["status"] = "stopped" if stopped else "completed"
    except Exception as e:
        logger.exception("Analysis failed for task %s: %s", task_id, e)
        await _mark_task_failed(task_id, str(e))
        if task_id in _progress_store:
            _progress_store[task_id]["status"] = "failed"
