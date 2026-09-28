import pytest
import httpx
from app.config import settings
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

    httpx_mock.add_callback(respond, is_reusable=True)

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

    httpx_mock.add_callback(respond, is_reusable=True)

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

    httpx_mock.add_callback(respond, is_reusable=True)

    results = await search_urls("Test", ["kw"])
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_urls_defaults_to_searxng(httpx_mock):
    ports = set()

    def respond(request):
        ports.add(request.url.port)
        assert request.url.params["pageno"] == "1"
        return httpx.Response(200, json={"results": [
            {"url": "https://example.com/x", "title": "X"},
        ]})

    httpx_mock.add_callback(respond, is_reusable=True)
    settings.search_max_pages = 1
    results = await search_urls("Test", ["k"])
    assert results[0]["url"] == "https://example.com/x"
    assert ports == {httpx.URL(settings.searxng_base_url).port}


@pytest.mark.asyncio
async def test_searxng_paginates_up_to_max_pages(httpx_mock):
    pages = []

    def respond(request):
        pages.append(request.url.params["pageno"])
        return httpx.Response(200, json={"results": []})

    httpx_mock.add_callback(respond, is_reusable=True)
    settings.search_max_pages = 2
    await search_urls("Obj", [], engine="searxng")
    n_queries = len(build_queries("Obj", []))
    assert pages == ["1", "2"] * n_queries


@pytest.mark.asyncio
async def test_searxng_empty_falls_back_to_openserp(httpx_mock):
    ports = []

    def respond(request):
        ports.append(request.url.port)
        if request.url.port == httpx.URL(settings.searxng_base_url).port:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={
            "results": [{"url": "https://blog.ru/p", "title": "Отзыв"}],
            "pagination": {"has_more": False},
        })

    httpx_mock.add_callback(respond, is_reusable=True)
    results = await search_urls("Obj", [], engine="searxng")
    assert httpx.URL(settings.openserp_base_url).port in ports
    assert [r["url"] for r in results] == ["https://blog.ru/p"]


@pytest.mark.asyncio
async def test_searxng_nonempty_does_not_fall_back(httpx_mock):
    ports = set()

    def respond(request):
        ports.add(request.url.port)
        return httpx.Response(200, json={"results": [
            {"url": "https://example.com/x", "title": "X"},
        ]})

    httpx_mock.add_callback(respond, is_reusable=True)
    await search_urls("Obj", [], engine="searxng")
    assert ports == {httpx.URL(settings.searxng_base_url).port}
