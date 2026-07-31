import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_index_returns_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_api_search_returns_task_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/search", json={
            "object_name": "Test Monastery",
            "keywords": "keyword1, keyword2",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"
