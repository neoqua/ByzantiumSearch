from app.page_dates import extract_publication_date, normalize_date


def test_normalize_iso_and_dots():
    assert normalize_date("2023-05-01T12:00:00+03:00") == "01.05.2023"
    assert normalize_date("2023-05-01") == "01.05.2023"
    assert normalize_date("1.5.2023") == "01.05.2023"
    assert normalize_date("") is None
    assert normalize_date("not-a-date") is None


def test_extract_og_published_time():
    html = """
    <html><head>
    <meta property="article:published_time" content="2021-03-15T08:00:00Z">
    </head><body><p>text</p></body></html>
    """
    assert extract_publication_date(html) == "15.03.2021"


def test_extract_json_ld_date_published():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"BlogPosting","datePublished":"2020-12-31"}
    </script>
    </head><body></body></html>
    """
    assert extract_publication_date(html) == "31.12.2020"


def test_extract_time_datetime():
    html = '<html><body><time datetime="2019-07-04">4 июля</time></body></html>'
    assert extract_publication_date(html) == "04.07.2019"


def test_extract_returns_none_without_markup():
    assert extract_publication_date("<html><body><p>нет даты</p></body></html>") is None
    assert extract_publication_date(None) is None
    assert extract_publication_date(b"") is None
