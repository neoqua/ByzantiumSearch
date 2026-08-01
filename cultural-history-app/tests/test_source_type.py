from app.source_type import classify_source, SOURCE_PRIORITY


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
