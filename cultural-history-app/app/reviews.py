import json
import re
from typing import Optional, Union

from bs4 import BeautifulSoup

from app.keyword_match import match_keywords
from app.fields import object_in_text
from app.page_dates import normalize_date

MIN_REVIEW_LEN = 80
MAX_REVIEWS_PER_PAGE = 15
EXCERPT_LEN = 420

_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")

_DOM_SELECTORS = (
    '[itemprop="review"]',
    '[itemtype*="Review"]',
    '[itemprop="reviewBody"]',
    ".review-container",
    ".reviewBody",
    ".review-body",
    "div.review",
    "article.review",
)


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def _author_name(node) -> Optional[str]:
    if isinstance(node, str):
        return _clean(node) or None
    if isinstance(node, dict):
        name = node.get("name") or node.get("givenName")
        return _clean(name) if name else None
    return None


def _from_jsonld(soup: BeautifulSoup) -> list[dict]:
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            types = node.get("@type")
            if not isinstance(types, list):
                types = [types] if types else []
            if any("Review" in str(t) for t in types if t):
                body = node.get("reviewBody") or node.get("description")
                text = _clean(body if isinstance(body, str) else "")
                if len(text) >= MIN_REVIEW_LEN:
                    found.append({
                        "text": text,
                        "title": _clean(node.get("name") if isinstance(node.get("name"), str) else "") or None,
                        "date": normalize_date(node.get("datePublished") if isinstance(node.get("datePublished"), str) else None),
                        "author": _author_name(node.get("author")),
                    })
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            walk(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return found


def _from_dom(soup: BeautifulSoup) -> list[dict]:
    found: list[dict] = []
    seen = set()
    for selector in _DOM_SELECTORS:
        for node in soup.select(selector):
            text = _clean(node.get_text(" ", strip=True))
            if len(text) < MIN_REVIEW_LEN or text in seen:
                continue
            seen.add(text)
            time_tag = node.find("time")
            date = None
            if time_tag and time_tag.get("datetime"):
                date = normalize_date(time_tag["datetime"])
            found.append({
                "text": text,
                "title": None,
                "date": date,
                "author": None,
            })
            if len(found) >= MAX_REVIEWS_PER_PAGE:
                return found
    return found


def _dedupe(units: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for unit in units:
        key = (unit.get("text") or "")[:240]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(unit)
    return out


def extract_reviews(html: Union[str, bytes, None], page_text: str = "") -> list[dict]:
    """Split a page into review-sized units. One page-long unit if nothing splits."""
    if html is None:
        if page_text and len(page_text) >= MIN_REVIEW_LEN:
            return [{"text": _clean(page_text), "title": None, "date": None, "author": None}]
        return []
    if isinstance(html, bytes) and not html.strip():
        return []
    if isinstance(html, str) and not html.strip():
        return []
    soup = BeautifulSoup(html, "lxml")
    units = _dedupe(_from_jsonld(soup) + _from_dom(soup))
    if units:
        return units[:MAX_REVIEWS_PER_PAGE]
    text = _clean(page_text) or _clean(soup.get_text(" ", strip=True))
    if text:
        return [{"text": text, "title": None, "date": None, "author": None}]
    return []


def local_excerpt(text: str, object_name: str, keywords: list[str]) -> Optional[str]:
    blob = text or ""
    if not blob:
        return None
    parts = [p.strip() for p in _SENTENCE_RE.split(blob) if p.strip()]
    if not parts:
        return blob[:EXCERPT_LEN] or None
    picked = []
    for sentence in parts:
        if object_in_text(sentence, object_name) or match_keywords(sentence, keywords)[0]:
            picked.append(sentence)
        if len(" ".join(picked)) >= EXCERPT_LEN:
            break
    chosen = " ".join(picked) if picked else parts[0]
    if len(chosen) > EXCERPT_LEN:
        chosen = chosen[: EXCERPT_LEN - 1].rsplit(" ", 1)[0] + "…"
    return chosen or None


def grounded_excerpt(candidate: Optional[str], text: str, object_name: str, keywords: list[str]) -> Optional[str]:
    raw = _clean(candidate)
    page = text or ""
    if raw and raw.lower() in page.lower():
        return raw[:EXCERPT_LEN]
    return local_excerpt(page, object_name, keywords)
