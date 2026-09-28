from app.source_type import (
    classify_source, SOURCE_PRIORITY, TRAVEL_BLOG_DOMAINS,
    is_travel_blog_host, count_source_mix, format_source_mix,
)


def test_ugc_domain():
    assert classify_source("https://user123.livejournal.com/1200.html", "") == "ugc"
    assert classify_source("https://otzovik.com/reviews/obj123/", "") == "ugc"


def test_ugc_domain():
    assert classify_source("https://user123.livejournal.com/1200.html", "") == "ugc"
    assert classify_source("https://otzovik.com/reviews/obj123/", "") == "ugc"


def test_ugc_url_marker():
    assert classify_source("https://example.com/otzyvy/123/", "Читать") == "ugc"
    assert classify_source("https://example.com/forum/thread/1", "Тема") == "ugc"


def test_ugc_title_marker():
    assert classify_source("https://example.com/123", "Отзыв о поездке") == "ugc"
    assert classify_source("https://example.com/123", "Блог про путешествия") == "ugc"


def test_official_domain():
    assert classify_source("https://hws.gov.ru/", "Официальный сайт") == "official"
    assert classify_source("https://example-museum.ru/", "Музей") == "official"


def test_official_title_marker():
    assert classify_source("https://example.com/", "Официальный сайт объекта") == "official"


def test_agency_title_marker():
    assert classify_source("https://example.com/", "Турагентство Сказка") == "agency"
    assert classify_source("https://example.com/", "Туроператор Экскурсии") == "agency"


def test_unknown():
    assert classify_source("https://news-site.ru/article/1", "Новости") == "unknown"


def test_priority_order():
    assert SOURCE_PRIORITY["ugc"] < SOURCE_PRIORITY["unknown"] < SOURCE_PRIORITY["official"] < SOURCE_PRIORITY["agency"]


def test_travel_blog_domains_loaded():
    assert "tourister.ru" in TRAVEL_BLOG_DOMAINS
    assert "livejournal.com" in TRAVEL_BLOG_DOMAINS
    assert len(TRAVEL_BLOG_DOMAINS) >= 10


def test_travel_blog_host_suffix_match():
    assert is_travel_blog_host("https://www.tourister.ru/reviews/1")
    assert is_travel_blog_host("https://user.livejournal.com/1.html")
    assert not is_travel_blog_host("https://example.com/forum/1")


def test_travel_blog_counts_as_ugc():
    assert classify_source("https://www.tourister.ru/x", "Гида") == "ugc"


def test_source_mix_counts_and_label():
    items = [
        {"url": "https://tourister.ru/a", "title": "", "source_type": "ugc", "travel_blog": True},
        {"url": "https://example.com/forum/1", "title": "Тема", "source_type": "ugc"},
        {"url": "https://x.gov.ru/", "title": "Официальный сайт", "source_type": "official"},
        {"url": "https://agency.example/", "title": "Турагентство", "source_type": "agency"},
        {"url": "https://news.example/1", "title": "Новости", "source_type": "unknown"},
    ]
    mix = count_source_mix(items)
    assert mix["ugc"] == 2
    assert mix["official"] == 1
    assert mix["agency"] == 1
    assert mix["unknown"] == 1
    assert mix["travel_blog"] == 1
    label = format_source_mix(mix)
    assert "блоги и отзывы: 2" in label
    assert "тревел-площадки: 1" in label
