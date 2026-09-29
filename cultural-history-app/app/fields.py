from typing import Optional

from app.keyword_match import match_keywords, stems_in_order
from app.page_dates import normalize_date
from app.source_type import classify_source, is_travel_blog_host

SOURCE_TYPE_LABELS = {
    "ugc": "блог/отзыв",
    "official": "официальный",
    "agency": "агентство",
    "unknown": "прочее",
}


def object_in_text(text: str, object_name: str) -> bool:
    if not object_name or not (text or "").strip():
        return False
    matched, _ = match_keywords(text, [object_name])
    if matched:
        return True
    return stems_in_order(text, object_name)


def location_grounded(location: str, text: str) -> bool:
    loc = (location or "").strip()
    if len(loc) < 2 or not text:
        return False
    if loc.lower() in {"null", "none", "нет", "n/a"}:
        return False
    if loc.lower() in text.lower():
        return True
    matched, _ = match_keywords(text, [loc])
    return bool(matched)


def grounded_location(location: str, text: str) -> Optional[str]:
    loc = (location or "").strip()
    if not loc or loc.lower() in {"null", "none", "нет", "n/a"}:
        return None
    if location_grounded(loc, text):
        return loc
    parts = [p.strip() for p in loc.replace(";", ",").split(",") if p.strip()]
    kept = [p for p in parts if location_grounded(p, text)]
    return ", ".join(kept) if kept else None


def relevance_score(mentions_object: bool, has_keyword: bool, url: str, title: str) -> float:
    if not mentions_object:
        return 0.0
    score = 0.5
    if has_keyword:
        score = 0.8
    if classify_source(url, title) == "ugc" or is_travel_blog_host(url):
        score = min(1.0, score + 0.2)
    return round(score, 2)


def format_source_type(code: str) -> str:
    return SOURCE_TYPE_LABELS.get(code or "", code or "—")


def heuristic_source_type(url: str, title: str) -> str:
    return classify_source(url, title)


def finalize_dates(page_date: str, llm_publication, llm_mentioned) -> dict:
    mentioned = normalize_date(llm_mentioned if isinstance(llm_mentioned, str) else None)
    if page_date:
        return {
            "publication_date": page_date,
            "date_source": "page",
            "date_mentioned": mentioned,
        }
    pub = normalize_date(llm_publication if isinstance(llm_publication, str) else None)
    if pub:
        return {
            "publication_date": pub,
            "date_source": "llm",
            "date_mentioned": mentioned,
        }
    return {
        "publication_date": None,
        "date_source": None,
        "date_mentioned": mentioned,
    }
