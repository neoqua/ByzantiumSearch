import pytest
import httpx
from app.search import search_urls, build_queries


def test_build_queries_contains_ugc_markers():
    queries = build_queries("TestObject", ["keyword1"])
    assert "TestObject" in queries
    assert "TestObject keyword1" in queries
    assert "TestObject отзывы" in queries
    assert "TestObject блог" in queries
    assert "TestObject форум" in queries
    assert "TestObject впечатления" in queries


@pytest.mark.asyncio
async def test_search_urls_returns_sorted_results(httpx_mock):
    def respond(request):
        q = request.url.params["q"]
        return httpx.Response(200, json={"results": [
            {"url": f"https://example.com/{q.replace(' ', '_')}", "title": q},
        ]})

    httpx_mock.add_callback(respond)

    results = await search_urls("TestObject", ["keyword1"])
    assert len(results) == len(build_queries("TestObject", ["keyword1"]))
    assert any(r["source_type"] == "ugc" for r in results)


@pytest.mark.asyncio
async def test_search_urls_prioritizes_ugc(httpx_mock):
    def respond(request):
        q = request.url.params["q"]
        if q == "TestObject":
            return httpx.Response(200, json={"results": [
                {"url": "https://example.com/", "title": "Турагентство"},
                {"url": "https://user.livejournal.com/1", "title": "Запись"},
            ]})
        return httpx.Response(200, json={"results": []})

    httpx_mock.add_callback(respond)

    results = await search_urls("TestObject", [])
    assert results[0]["source_type"] == "ugc"
    assert results[1]["source_type"] == "agency"


@pytest.mark.asyncio
async def test_search_urls_deduplicates(httpx_mock):
    def respond(request):
        return httpx.Response(200, json={"results": [
            {"url": "https://example.com/dup", "title": "Dup"},
            {"url": "https://example.com/new", "title": "New"},
        ]})

    httpx_mock.add_callback(respond)

    results = await search_urls("Test", ["kw"])
    assert len(results) == 2
