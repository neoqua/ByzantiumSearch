import pytest
import httpx
from app.search import search_urls
from app.source_type import UGC_QUERY_MARKERS


@pytest.mark.asyncio
async def test_openserp_request_shape(httpx_mock):
    captured = {}

    def respond(request):
        captured.setdefault("params", dict(request.url.params))
        return httpx.Response(200, json={
            "results": [
                {"url": "https://blog.ru/post1", "title": "Отзыв", "rank": 1, "domain": "blog.ru"},
            ],
            "pagination": {"page": 1, "has_more": False, "next_start": 30},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("TestObject", ["kw1"], engine="openserp")
    assert captured["params"]["text"] == "TestObject"
    assert captured["params"]["engines"] == "google,yandex,duckduckgo"
    assert captured["params"]["mode"] == "balanced"
    assert captured["params"]["limit"] == "30"
    assert captured["params"]["start"] == "0"
    assert results[0]["url"] == "https://blog.ru/post1"
    assert results[0]["source_type"] == "ugc"


@pytest.mark.asyncio
async def test_openserp_paginates(httpx_mock):
    calls = []

    def respond(request):
        start = request.url.params["start"]
        calls.append(start)
        if start == "0":
            return httpx.Response(200, json={
                "results": [{"url": f"https://a/{i}", "title": "t"} for i in range(2)],
                "pagination": {"page": 1, "has_more": True, "next_start": 30},
            })
        return httpx.Response(200, json={
            "results": [{"url": f"https://b/{i}", "title": "t"} for i in range(2)],
            "pagination": {"page": 2, "has_more": False, "next_start": 60},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    n_queries = 1 + len(UGC_QUERY_MARKERS)  # object name + one query per UGC marker
    assert len(calls) == 2 * n_queries
    assert calls == ["0", "30"] * n_queries
    assert len(results) == 4


@pytest.mark.asyncio
async def test_openserp_dedups_across_pages(httpx_mock):
    def respond(request):
        if request.url.params["start"] == "0":
            return httpx.Response(200, json={
                "results": [{"url": "https://a/dup", "title": "t"}],
                "pagination": {"has_more": True, "next_start": 30},
            })
        return httpx.Response(200, json={
            "results": [{"url": "https://a/dup", "title": "t"}],
            "pagination": {"has_more": False, "next_start": 60},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_openserp_limit_cap_stops_at_five_rounds(httpx_mock):
    def respond(request):
        return httpx.Response(200, json={
            "results": [{"url": "https://a/dup", "title": "t"}],
            "pagination": {"has_more": True, "next_start": 30},
        })

    httpx_mock.add_callback(respond)
    results = await search_urls("Obj", [], engine="openserp")
    assert len(results) == 1  # 5 rounds, all deduped, loop capped
