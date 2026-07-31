import os
import tempfile
import uuid

_test_db_path = os.path.join(tempfile.gettempdir(), f"task9_integration_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db
from app import main as main_module


async def _noop_run_analysis(*args, **kwargs):
    pass


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    await init_db()
    monkeypatch.setattr(main_module, "run_analysis", _noop_run_analysis)
    yield


@pytest.mark.asyncio
async def test_full_api_flow(setup_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create search task
        resp = await client.post("/api/search", json={
            "object_name": "Test Monastery",
            "keywords": "test_kw",
            "annual_visitors": 1000,
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Check progress endpoint exists
        resp = await client.get(f"/api/tasks/{task_id}/progress")
        assert resp.status_code == 200

        # Check results page renders (task may still be processing)
        resp = await client.get(f"/results/{task_id}")
        assert resp.status_code == 200
