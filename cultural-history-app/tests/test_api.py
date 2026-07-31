import os
import tempfile
import uuid

_test_db_path = os.path.join(tempfile.gettempdir(), f"task6_test_api_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db
from app import main as main_module


async def _noop_run_analysis(*args, **kwargs):
    pass


@pytest.fixture
async def api_client(monkeypatch):
    await init_db()
    monkeypatch.setattr(main_module, "run_analysis", _noop_run_analysis)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_index_returns_html(api_client):
    resp = await api_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_api_search_returns_task_id(api_client):
    resp = await api_client.post("/api/search", json={
        "object_name": "Test Monastery",
        "keywords": "keyword1, keyword2",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"
