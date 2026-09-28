import json
from pathlib import Path
from urllib.parse import urlparse

SOURCE_PRIORITY = {"ugc": 0, "unknown": 1, "official": 2, "agency": 3}

UGC_QUERY_MARKERS = [
    "отзывы", "блог", "форум", "впечатления",
    "путеводитель", "путешествие",
]

_UGC_DOMAIN_MARKERS = (
    "livejournal.com", "lj.ru", "otzovik.com", "irecommend.ru",
    "dzen.ru", "pikabu.ru", "tripadvisor.ru", "tripadvisor.com",
    "vk.com", "vkontakte.ru", "t.me", "blogspot.com", "blogspot.ru",
    "tumblr.com", "drive2.ru", "otzyv.ru", "forum", "sibmama.ru",
    "yaplakal.com", "fishki.net", "e1.ru",
)

_UGC_URL_MARKERS = ("/blog", "/forum", "/otzyv", "/reviews", "/comments", "/obzor")

_UGC_TITLE_MARKERS = (
    "отзыв", "блог", "форум", "впечатления", "дневник",
    "рассказ", "путешеств", "поездк", "посетил", "впечатлен",
)

_OFFICIAL_URL_MARKERS = (".gov", "museum", "министерство", "правительство")

_OFFICIAL_TITLE_MARKERS = (
    "официальный сайт", "официальный портал", "официальный",
    "государств", "правительство", "министерство",
)

_AGENCY_TITLE_MARKERS = (
    "турагент", "туроператор", "турфирм", "купить тур",
    "бронирование", "туры от", "экскурсии от", "агентств",
)

_MIX_KEYS = ("ugc", "official", "agency", "unknown", "travel_blog")


def _load_travel_blog_domains():
    path = Path(__file__).resolve().parent / "travel_blog_domains.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    domains = []
    seen = set()
    for raw in data.get("domains") or []:
        host = str(raw).strip().lower().lstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if host and host not in seen:
            seen.add(host)
            domains.append(host)
    return tuple(domains)


TRAVEL_BLOG_DOMAINS = _load_travel_blog_domains()


def _host(url: str) -> str:
    host = urlparse((url or "").lower()).netloc
    if host.startswith("www."):
        host = host[4:]
    return host


def is_travel_blog_host(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    for domain in TRAVEL_BLOG_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def classify_source(url: str, title: str) -> str:
    url_l = (url or "").lower()
    host = _host(url)
    title_l = (title or "").lower()

    if is_travel_blog_host(url):
        return "ugc"
    if any(m in host for m in _UGC_DOMAIN_MARKERS):
        return "ugc"
    if any(m in url_l for m in _UGC_URL_MARKERS):
        return "ugc"
    if any(m in title_l for m in _UGC_TITLE_MARKERS):
        return "ugc"

    if any(m in title_l for m in _AGENCY_TITLE_MARKERS):
        return "agency"

    if any(m in host for m in _OFFICIAL_URL_MARKERS):
        return "official"
    if any(m in title_l for m in _OFFICIAL_TITLE_MARKERS):
        return "official"

    return "unknown"


def count_source_mix(items) -> dict:
    counts = {k: 0 for k in _MIX_KEYS}
    for item in items or []:
        url = (item or {}).get("url") or ""
        title = (item or {}).get("title") or ""
        st = (item or {}).get("source_type") or classify_source(url, title)
        if st not in ("ugc", "official", "agency"):
            st = "unknown"
        counts[st] += 1
        if (item or {}).get("travel_blog") or is_travel_blog_host(url):
            counts["travel_blog"] += 1
    return counts


def format_source_mix(mix) -> str:
    if not mix:
        return ""
    parts = [
        f"блоги и отзывы: {int(mix.get('ugc') or 0)}",
        f"официальные: {int(mix.get('official') or 0)}",
        f"агентства: {int(mix.get('agency') or 0)}",
        f"прочие: {int(mix.get('unknown') or 0)}",
    ]
    travel = int(mix.get("travel_blog") or 0)
    text = ", ".join(parts)
    if travel:
        text += f" (тревел-площадки: {travel})"
    return text
