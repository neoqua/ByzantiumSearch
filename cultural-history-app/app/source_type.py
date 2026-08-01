from urllib.parse import urlparse

SOURCE_PRIORITY = {"ugc": 0, "unknown": 1, "official": 2, "agency": 3}

UGC_QUERY_MARKERS = ["отзывы", "блог", "форум", "впечатления"]

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


def classify_source(url: str, title: str) -> str:
    url_l = url.lower()
    host = urlparse(url_l).netloc
    title_l = (title or "").lower()

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
