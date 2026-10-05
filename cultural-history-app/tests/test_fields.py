import pytest
from app.fields import (
    object_in_text,
    location_grounded,
    relevance_score,
    format_source_type,
    finalize_dates,
)
from app.scraper import fetch_and_analyze


def test_object_in_text_uses_stems():
    assert object_in_text("Посетили Свято-Климентовский монастырь летом", "Климентовский монастырь")
    assert object_in_text(
        "Свято-Климентовский мужской монастырь в Инкермане",
        "Свято-Климентовский монастырь",
    )
    assert not object_in_text("Погода в Крыму отличная", "Климентовский монастырь")


def test_location_requires_tokens_in_page():
    text = "Автор живёт в Севастополе и пишет о поездке"
    assert location_grounded("Севастополь", text)
    assert not location_grounded("Москва", text)
    assert not location_grounded("  ", text)
    assert not location_grounded("null", text)


def test_grounded_location_keeps_matching_parts():
    from app.fields import grounded_location
    text = "Поездка в Севастополь к монастырю"
    assert grounded_location("Севастополь, Россия, Крым", text) == "Севастополь"
    assert grounded_location("Париж", text) is None
    assert grounded_location("null", text) is None


def test_relevance_formula():
    assert relevance_score(False, True, "https://otzyv.ru/x", "блог") == 0.0
    assert relevance_score(True, False, "https://museum.gov.ru/x", "Официальный сайт") == 0.5
    assert relevance_score(True, True, "https://museum.gov.ru/x", "Официальный сайт") == 0.8
    ugc = relevance_score(True, True, "https://otzyv.ru/post", "Отзыв туриста")
    assert ugc == 1.0


def test_format_source_type_labels():
    assert format_source_type("ugc") == "блог/отзыв"
    assert format_source_type("official") == "официальный"
    assert format_source_type("blog") == "blog"


def test_finalize_dates_prefers_page():
    dates = finalize_dates("15.03.2021", "01.01.1999", "05.05.2020")
    assert dates["publication_date"] == "15.03.2021"
    assert dates["date_source"] == "page"
    assert dates["date_mentioned"] == "05.05.2020"


@pytest.mark.asyncio
async def test_prefilter_skips_llm(monkeypatch):
    called = {"llm": 0}

    async def page(url, client=None):
        return "<p>Прогноз погоды на выходные</p>".encode("utf-8")

    async def llm(*args, **kwargs):
        called["llm"] += 1
        raise AssertionError("LLM must not run for prefiltered pages")

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm)
    result = await fetch_and_analyze(
        "https://news.example/weather", "Климентовский монастырь", ["Византия"], "Погода"
    )
    assert result["analysis_status"] == "prefiltered"
    assert result["mentions_object"] is False
    assert result["has_keyword"] is False
    assert called["llm"] == 0


@pytest.mark.asyncio
async def test_title_with_object_does_not_prefilter(monkeypatch):
    called = {"llm": 0}

    async def page(url, client=None):
        return "<p>Короткий шаблон без тела</p>".encode("utf-8")

    async def llm(*args, **kwargs):
        called["llm"] += 1
        return {
            "mentions_object": True,
            "publication_date": None,
            "date_mentioned": None,
            "author_location": None,
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm)
    result = await fetch_and_analyze(
        "https://vk.com/wall-1",
        "Климентовский монастырь",
        ["Византия"],
        "Свято-Климентовский монастырь в Инкермане",
    )
    assert called["llm"] == 1
    assert result["analysis_status"] == "ok"
    assert result["mentions_object"] is True


@pytest.mark.asyncio
async def test_disputed_when_object_stem_but_llm_says_no(monkeypatch):
    async def page(url, client=None):
        return "<p>Свято-Климентовский монастырь в Инкермане</p>".encode("utf-8")

    async def llm(*args, **kwargs):
        return {
            "mentions_object": False,
            "publication_date": None,
            "date_mentioned": "01.06.2024",
            "author_location": "Инкерман",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm)
    result = await fetch_and_analyze(
        "https://otzyv.ru/post", "Климентовский монастырь", ["Византия"], "Отзыв"
    )
    assert result["analysis_status"] == "disputed"
    assert result["mentions_object"] is False
    assert result["date_mentioned"] == "01.06.2024"
    assert result["author_location"] is None
    assert result["source_type"] == "ugc"


@pytest.mark.asyncio
async def test_geo_dropped_if_not_on_page(monkeypatch):
    async def page(url, client=None):
        return "<p>Климентовский монастырь. Византия в истории места.</p>".encode("utf-8")

    async def llm(*args, **kwargs):
        return {
            "mentions_object": True,
            "publication_date": None,
            "date_mentioned": None,
            "author_location": "Париж",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm)
    result = await fetch_and_analyze(
        "https://museum.example/x", "Климентовский монастырь", ["Византия"], "Статья"
    )
    assert result["analysis_status"] == "ok"
    assert result["mentions_object"] is True
    assert result["author_location"] is None
    assert result["has_keyword"] is True
    assert result["relevance_score"] == 0.8


def test_content_kind_and_period_overlay():
    from app.fields import classify_content_kind, overlay_filters, date_in_period, period_cutoff
    from datetime import datetime, timezone

    assert classify_content_kind("https://otzovik.com/review/1", "Отзыв") == "personal_review"
    assert classify_content_kind("https://ru.wikipedia.org/wiki/X", "Статья") == "description"
    assert classify_content_kind("https://agency.example/", "Турагентство") == "promo"

    cutoff = datetime(2025, 9, 1, tzinfo=timezone.utc)
    assert date_in_period("15.10.2025", cutoff) is True
    assert date_in_period("01.01.2024", cutoff) is False
    assert date_in_period(None, cutoff) is None
    assert period_cutoff(0) is None

    row = overlay_filters(
        {"analysis_status": "ok", "mentions_object": True, "content_kind": "description",
         "publication_date": "01.10.2025", "relevance_score": 0.8},
        "personal", cutoff,
    )
    assert row["analysis_status"] == "not_personal"
    old = overlay_filters(
        {"analysis_status": "ok", "mentions_object": True, "content_kind": "personal_review",
         "publication_date": "01.01.2020", "relevance_score": 0.8},
        "personal", cutoff,
    )
    assert old["analysis_status"] == "out_of_period"
    undated = overlay_filters(
        {"analysis_status": "ok", "mentions_object": True, "content_kind": "personal_review",
         "publication_date": None, "relevance_score": 0.8},
        "personal", cutoff,
    )
    assert undated["analysis_status"] == "undated"
    assert undated["mentions_object"] is True
