import pytest
from app.search import search_urls


@pytest.mark.asyncio
async def test_search_urls_returns_list(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=TestObject&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/post1", "title": "Post 1"},
                {"url": "https://example.com/post2", "title": "Post 2"},
            ]
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=TestObject%20keyword1&format=json&language=ru-RU&categories=general",
        json={"results": []},
    )

    results = await search_urls("TestObject", ["keyword1"])
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/post1"
    assert results[1]["url"] == "https://example.com/post2"


@pytest.mark.asyncio
async def test_search_urls_deduplicates(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=Test&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/dup", "title": "Dup"},
            ]
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8888/search?q=Test%20kw&format=json&language=ru-RU&categories=general",
        json={
            "results": [
                {"url": "https://example.com/dup", "title": "Dup"},
                {"url": "https://example.com/new", "title": "New"},
            ]
        },
    )

    results = await search_urls("Test", ["kw"])
    assert len(results) == 2
