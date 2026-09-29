import hashlib
import logging
from typing import Optional, Union
import httpx
from bs4 import BeautifulSoup
from app.config import settings
from app.llm import analyze_text_with_retry
from app.keyword_match import match_keywords
from app.page_dates import extract_publication_date
from app.fields import (
    object_in_text,
    grounded_location,
    relevance_score,
    heuristic_source_type,
    finalize_dates,
)
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
    dates = finalize_dates(None, None, None)
    return {
        "url": url,
        "title": title,
        "mentions_object": False,
        "has_keyword": False,
        "keyword_found": None,
        "author_location": None,
        "source_type": heuristic_source_type(url, title),
        "relevance_score": 0.0,
        "raw_text_hash": None,
        "analysis_status": status,
        **dates,
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
    blob = f"{title or ''} {text}"
    matched_kw, matched_forms = match_keywords(blob, keywords)
    has_kw = bool(matched_kw)
    obj_hit = object_in_text(blob, object_name)
    source_type = heuristic_source_type(url, title)
    keyword_found = ", ".join(matched_forms) if matched_forms else None

    if not obj_hit and not has_kw:
        dates = finalize_dates(page_date, None, None)
        return {
            "url": url,
            "title": title,
            "mentions_object": False,
            "has_keyword": False,
            "keyword_found": None,
            "author_location": None,
            "source_type": source_type,
            "relevance_score": 0.0,
            "raw_text_hash": h,
            "analysis_status": "prefiltered",
            **dates,
        }

    llm_result = await analyze_text_with_retry(
        object_name, keywords, title, text, llm_settings=llm_settings
    )
    status = llm_result.get("analysis_status") or "ok"
    mentions = bool(llm_result.get("mentions_object")) if status == "ok" else False
    if status == "ok" and obj_hit and not mentions:
        status = "disputed"
        mentions = False

    location = llm_result.get("author_location") if status == "ok" else None
    if location:
        location = grounded_location(str(location), blob)

    dates = finalize_dates(
        page_date,
        llm_result.get("publication_date") if status == "ok" else None,
        llm_result.get("date_mentioned") if status in ("ok", "disputed") else None,
    )
    return {
        "url": url,
        "title": title,
        "mentions_object": mentions,
        "has_keyword": has_kw,
        "keyword_found": keyword_found,
        "author_location": location,
        "source_type": source_type,
        "relevance_score": relevance_score(mentions, has_kw, url, title),
        "raw_text_hash": h,
        "analysis_status": status,
        **dates,
    }
