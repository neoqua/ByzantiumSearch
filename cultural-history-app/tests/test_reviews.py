import json

import pytest

from app.reviews import extract_reviews, grounded_excerpt, local_excerpt
from app.scraper import fetch_and_analyze

_R1 = (
    "Были в Свято-Климентовском монастыре в сентябре. Пещеры произвели сильное "
    "впечатление, но очереди к кассе утомляют."
)
_R2 = (
    "Свято-Климентовский монастырь стоит увидеть ради фресок. Византия здесь "
    "ощущается в каждой нише, хотя сервис слабый."
)


def test_extract_reviews_from_jsonld():
    payload = [
        {
            "@type": "Review",
            "reviewBody": _R1,
            "datePublished": "2024-06-01",
            "author": {"name": "Анна"},
        },
        {
            "@type": "Review",
            "reviewBody": _R2,
            "datePublished": "2023-01-10",
        },
    ]
    html = f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
    units = extract_reviews(html)
    assert len(units) == 2
    assert units[0]["date"] == "01.06.2024"
    assert units[0]["author"] == "Анна"
    assert "пещеры" in units[0]["text"].lower()


def test_extract_reviews_from_dom():
    html = f"""
    <div itemprop="review"><p>{_R1}</p></div>
    <div class="review-body">{_R2}</div>
    """
    units = extract_reviews(html)
    assert len(units) == 2


def test_blog_page_stays_one_unit():
    html = f"<article><p>{_R1} {_R2}</p></article>"
    units = extract_reviews(html, page_text=_R1 + " " + _R2)
    assert len(units) == 1


def test_local_excerpt_picks_object_sentence():
    text = (
        "Погода была пасмурной. Свято-Климентовский монастырь открыт с утра. "
        "Потом поехали на пляж."
    )
    excerpt = local_excerpt(text, "Климентовский монастырь", ["Византия"])
    assert excerpt is not None
    assert "монастырь" in excerpt.lower()
    assert "пляж" not in excerpt


def test_grounded_excerpt_rejects_hallucination():
    text = "Свято-Климентовский монастырь стоит на скале над бухтой."
    got = grounded_excerpt("В Париже отличный круассан", text, "Климентовский монастырь", [])
    assert got is not None
    assert "париже" not in got.lower()
    assert "монастырь" in got.lower()


@pytest.mark.asyncio
async def test_fetch_and_analyze_one_row_per_review(monkeypatch):
    payload = [
        {"@type": "Review", "reviewBody": _R1, "datePublished": "2024-06-01"},
        {"@type": "Review", "reviewBody": _R2, "datePublished": "2023-01-10"},
    ]
    html = (
        '<html><body>'
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</body></html>"
    ).encode("utf-8")
    called = {"n": 0}

    async def page(url, client=None):
        return html

    async def llm(*args, **kwargs):
        called["n"] += 1
        return {
            "mentions_object": True,
            "publication_date": None,
            "date_mentioned": None,
            "author_location": None,
            "excerpt": None,
            "impression": f"смысл {called['n']}",
            "analysis_status": "ok",
        }

    monkeypatch.setattr("app.scraper.fetch_page_bytes", page)
    monkeypatch.setattr("app.scraper.analyze_text_with_retry", llm)
    rows = await fetch_and_analyze(
        "https://otzyv.ru/listing",
        "Климентовский монастырь",
        ["Византия"],
        "Отзывы",
    )
    assert called["n"] == 2
    assert len(rows) == 2
    assert rows[0]["publication_date"] == "01.06.2024"
    assert rows[0]["date_source"] == "page"
    assert rows[0]["impression"] == "смысл 1"
    assert rows[0]["excerpt"]
    assert "монастыр" in rows[0]["excerpt"].lower()
    assert rows[1]["publication_date"] == "10.01.2023"
