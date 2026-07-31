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
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
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
