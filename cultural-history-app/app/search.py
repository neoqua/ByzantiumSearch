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
