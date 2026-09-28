import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
import httpx
from app.config import settings
from app.source_type import (
    classify_source, SOURCE_PRIORITY, UGC_QUERY_MARKERS, is_travel_blog_host,
)

logger = logging.getLogger(__name__)

OnSearchProgress = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]


async def _notify_search_progress(
    on_progress: OnSearchProgress, payload: Dict[str, Any]
) -> None:
    if on_progress is None:
        return
    result = on_progress(payload)
    if asyncio.iscoroutine(result):
        await result


def build_queries(object_name: str, keywords: List[str]) -> List[str]:
    queries = [object_name]
    for kw in keywords:
        queries.append(f"{object_name} {kw}")
    for marker in UGC_QUERY_MARKERS:
        queries.append(f"{object_name} {marker}")
    return queries


def _sort_key(item: Dict[str, Any]) -> tuple:
    if item.get("travel_blog"):
        return (0, 0)
    return (1, SOURCE_PRIORITY.get(item.get("source_type", "unknown"), 1))


def _extract(item: Dict) -> Dict[str, Any]:
    url = item.get("url", "").strip()
    title = item.get("title", "")
    return {
        "url": url,
        "title": title,
        "source_type": classify_source(url, title),
        "travel_blog": is_travel_blog_host(url),
    }


async def _search_searxng(
    object_name: str,
    keywords: List[str],
    on_progress: OnSearchProgress = None,
) -> List[Dict[str, str]]:
    queries = build_queries(object_name, keywords)
    seen_urls: set = set()
    results: List[Dict[str, str]] = []
    n_queries = len(queries)

    delay = settings.search_delay_between_queries
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, query in enumerate(queries):
            await _notify_search_progress(on_progress, {
                "engine": "searxng",
                "query": query,
                "index": i + 1,
                "total": n_queries,
                "urls_found": len(results),
            })
            if i > 0:
                await asyncio.sleep(delay)
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
                    await _notify_search_progress(on_progress, {
                        "engine": "searxng",
                        "query": query,
                        "index": i + 1,
                        "total": n_queries,
                        "urls_found": len(results),
                    })
            except Exception as e:
                logger.warning("Search query '%s' failed: %s", query, e)
    return results


async def _search_openserp(
    object_name: str,
    keywords: List[str],
    on_progress: OnSearchProgress = None,
) -> List[Dict[str, str]]:
    queries = build_queries(object_name, keywords)
    seen_urls: set = set()
    results: List[Dict[str, str]] = []
    n_queries = len(queries)
    engines = settings.openserp_engines
    mode = settings.openserp_mode
    limit = settings.openserp_results_limit

    delay = settings.search_delay_between_queries
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, query in enumerate(queries):
            await _notify_search_progress(on_progress, {
                "engine": "openserp",
                "query": query,
                "index": i + 1,
                "total": n_queries,
                "urls_found": len(results),
            })
            if i > 0:
                await asyncio.sleep(delay)
            try:
                start = 0
                for _round in range(settings.search_max_pages):
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
                    await _notify_search_progress(on_progress, {
                        "engine": "openserp",
                        "query": query,
                        "index": i + 1,
                        "total": n_queries,
                        "urls_found": len(results),
                    })
                    pagination = data.get("pagination") or {}
                    if not pagination.get("has_more"):
                        break
                    start = pagination.get("next_start", start + limit)
            except Exception as e:
                logger.warning("OpenSERP query '%s' failed: %s", query, e)
    return results


async def search_urls(
    object_name: str,
    keywords: List[str],
    engine: str = "searxng",
    on_progress: OnSearchProgress = None,
) -> List[Dict[str, str]]:
    results, _used, _fallback = await search_urls_detailed(
        object_name, keywords, engine=engine, on_progress=on_progress
    )
    return results


async def search_urls_detailed(
    object_name: str,
    keywords: List[str],
    engine: str = "searxng",
    on_progress: OnSearchProgress = None,
) -> tuple:
    """Return (results, engine_used, fallback_from_searxng)."""
    if engine == "searxng":
        results = await _search_searxng(
            object_name, keywords, on_progress=on_progress
        )
        if not results:
            logger.warning(
                "SearXNG returned 0 results, falling back to OpenSERP"
            )
            await _notify_search_progress(on_progress, {
                "engine": "openserp",
                "query": "SearXNG пуст, переход на OpenSERP",
                "index": 0,
                "total": len(build_queries(object_name, keywords)),
                "urls_found": 0,
            })
            results = await _search_openserp(
                object_name, keywords, on_progress=on_progress
            )
            results.sort(key=_sort_key)
            return results, "openserp", True
        results.sort(key=_sort_key)
        return results, "searxng", False
    results = await _search_openserp(
        object_name, keywords, on_progress=on_progress
    )
    results.sort(key=_sort_key)
    return results, "openserp", False
