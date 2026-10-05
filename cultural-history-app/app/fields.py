from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from app.keyword_match import match_keywords, stems_in_order
from app.page_dates import normalize_date
from app.source_type import classify_source, is_travel_blog_host

SOURCE_TYPE_LABELS = {
    "ugc": "блог/отзыв",
    "official": "официальный",
    "agency": "агентство",
    "unknown": "прочее",
}

CONTENT_KIND_LABELS = {
    "personal_review": "личный отзыв",
    "description": "описание",
    "promo": "реклама/заказной",
    "other": "прочее",
}

_CONTENT_KINDS = frozenset(CONTENT_KIND_LABELS)
_WIKI_HINTS = ("wikipedia.org", "wikipedia.ru", "wiki/")
_PROMO_HINTS = (
    "купить тур", "турагентств", "туроператор", "бронирование",
    "экскурсии от", "туры от",
)


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


def format_content_kind(code: str) -> str:
    return CONTENT_KIND_LABELS.get(code or "", code or "—")


def period_cutoff(years: Optional[int], now: Optional[datetime] = None) -> Optional[datetime]:
    if not years:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        return now.replace(year=now.year - years, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return now.replace(
            year=now.year - years, month=2, day=28,
            hour=0, minute=0, second=0, microsecond=0,
        )


def cutoff_iso(cutoff: Optional[datetime]) -> Optional[str]:
    if cutoff is None:
        return None
    return cutoff.strftime("%Y-%m-%d")


def parse_cutoff_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        y, m, d = value.split("-")
        return datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def period_label(years: Optional[int]) -> str:
    if not years:
        return "без ограничения"
    if years == 1:
        return "за последний год"
    if years == 2:
        return "за 2 года"
    return f"за {years} лет"


def parse_publication_dt(value: Optional[str]) -> Optional[datetime]:
    text = normalize_date(value)
    if not text:
        return None
    day, month, year = text.split(".")
    return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)


def date_in_period(value: Optional[str], cutoff: Optional[datetime]) -> Optional[bool]:
    if cutoff is None:
        return True
    dt = parse_publication_dt(value)
    if dt is None:
        return None
    return dt >= cutoff


def classify_content_kind(url: str, title: str, text: str = "") -> str:
    host = urlparse((url or "").lower()).netloc
    if host.startswith("www."):
        host = host[4:]
    url_l = (url or "").lower()
    if any(h in host or h in url_l for h in _WIKI_HINTS):
        return "description"
    st = classify_source(url, title)
    if st == "agency":
        return "promo"
    if st == "official":
        return "description"
    blob = f"{title or ''} {text or ''}".lower()
    if any(h in blob for h in _PROMO_HINTS):
        return "promo"
    if st == "ugc" or is_travel_blog_host(url):
        return "personal_review"
    return "other"


def coerce_content_kind(value) -> str:
    kind = value if isinstance(value, str) else ""
    kind = kind.strip().lower().replace("-", "_")
    aliases = {
        "review": "personal_review",
        "personal": "personal_review",
        "отзыв": "personal_review",
        "описание": "description",
        "реклама": "promo",
    }
    kind = aliases.get(kind, kind)
    if kind not in _CONTENT_KINDS:
        return "other"
    return kind


def overlay_filters(data: dict, content_scope: str, cutoff: Optional[datetime]) -> dict:
    row = dict(data)
    status = row.get("analysis_status") or "ok"
    if status in ("fetch_failed", "llm_failed", "prefiltered"):
        return row
    kind = row.get("content_kind")
    if content_scope == "personal" and kind and kind != "personal_review":
        row["analysis_status"] = "not_personal"
        row["mentions_object"] = False
        row["relevance_score"] = 0.0
        return row
    inside = date_in_period(row.get("publication_date"), cutoff)
    if inside is False:
        row["analysis_status"] = "out_of_period"
        row["mentions_object"] = False
        row["relevance_score"] = 0.0
        return row
    if cutoff is not None and inside is None and status in ("ok", "disputed"):
        row["analysis_status"] = "undated"
    return row
