import os
import tempfile
import uuid
import asyncio

_test_db_path = os.path.join(tempfile.gettempdir(), f"task6_test_api_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db
from app import main as main_module
from app.schemas import ReportData, AnalysisResult


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


def test_report_data_accepts_status():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[], status="stopped",
    )
    assert r.status == "stopped"


def test_analysis_result_accepts_source_type():
    r = AnalysisResult(url="https://x", source_type="blog")
    assert r.source_type == "blog"


def test_report_build_passes_source_type(monkeypatch):
    from app.models import Result

    result_row = Result(
        task_id="t",
        url="https://x",
        title="t",
        mentions_object=True,
        has_keyword=True,
        keyword_found="kw",
        relevance_score=1.0,
        source_type="blog",
    )

    class _Task:
        id = "t"
        object_name = "o"
        keywords = "k"
        annual_visitors = None
        status = "completed"

    class _Session:
        async def get(self, model, task_id):
            return _Task()

        async def execute(self, stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return [result_row]
                    return _S()
            return _R()
    from app.report import build_report
    report = asyncio.run(build_report("t", _Session()))
    assert report.results[0].source_type == "blog"


@pytest.mark.asyncio
async def test_stop_returns_stopping(api_client):
    resp = await api_client.post("/api/tasks/nonexistent/stop")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stop_sets_flag(api_client):
    resp = await api_client.post("/api/search", json={
        "object_name": "Obj", "keywords": "kw",
    })
    task_id = resp.json()["task_id"]
    stop = await api_client.post(f"/api/tasks/{task_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopping"
    from app.analyzer import _progress_store
    assert _progress_store[task_id]["stop_requested"] is True


@pytest.mark.asyncio
async def test_llm_test_endpoint_ok(monkeypatch):
    class FakeProvider:
        async def complete(self, prompt):
            return "OK"

    def fake_get_provider(settings):
        return FakeProvider()

    monkeypatch.setattr(main_module, "get_provider", fake_get_provider)
    from app.main import app as main_app
    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/llm/test", json={
            "provider": "yandex", "api_key": "k", "folder_id": "f",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_llm_test_endpoint_invalid(api_client):
    resp = await api_client.post("/api/llm/test", json={
        "provider": "openai", "endpoint": "https://x/v1", "model": "m",
    })
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
