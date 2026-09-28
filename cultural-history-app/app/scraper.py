import hashlib
import logging
from typing import Optional, Union
import httpx
from bs4 import BeautifulSoup
from app.config import settings
from app.llm import analyze_text_with_retry
from app.keyword_match import match_keywords
from app.page_dates import extract_publication_date
from app.schemas import LLMSettings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
}


def extract_text(html: Union[str, bytes, None]) -> str:
    if html is None:
        return ""
    if isinstance(html, bytes):
        if not html.strip():
            return ""
        soup = BeautifulSoup(html, "lxml")
    else:
        if not html.strip():
            return ""
        soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blank_analysis(url: str, title: str, status: str) -> dict:
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
        "analysis_status": status,
        "date_source": None,
    }


def make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0,
        verify=settings.scraper_verify_ssl,
        follow_redirects=True,
        headers=_HEADERS,
    )


async def fetch_page_bytes(
    url: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[bytes]:
    own = client is None
    if own:
        client = make_http_client()
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None
        return resp.content or None
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None
    finally:
        if own:
            await client.aclose()


async def fetch_page_text(
    url: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    raw = await fetch_page_bytes(url, client=client)
    if not raw:
        return None
    return extract_text(raw) or None


async def fetch_and_analyze(
    url: str, object_name: str, keywords: list[str], title: str,
    llm_settings: Optional[LLMSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    raw = await fetch_page_bytes(url, client=client)
    if not raw:
        return _blank_analysis(url, title, "fetch_failed")
    text = extract_text(raw) or None
    if not text:
        return _blank_analysis(url, title, "fetch_failed")
    h = text_hash(text)
    page_date = extract_publication_date(raw)
    llm_result = await analyze_text_with_retry(
        object_name, keywords, title, text, llm_settings=llm_settings
    )
    llm_result.setdefault("source_type", "other")
    llm_result["url"] = url
    llm_result["title"] = title
    llm_result["raw_text_hash"] = h
    matched_kw, matched_forms = match_keywords(text, keywords)
    llm_result["has_keyword"] = bool(matched_kw)
    llm_result["keyword_found"] = ", ".join(matched_forms) if matched_forms else None
    llm_result.setdefault("analysis_status", "ok")
    if page_date:
        llm_result["publication_date"] = page_date
        llm_result["date_source"] = "page"
    elif llm_result.get("publication_date"):
        llm_result["date_source"] = "llm"
    else:
        llm_result["date_source"] = None
    return llm_result
