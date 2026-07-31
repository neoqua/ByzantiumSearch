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
