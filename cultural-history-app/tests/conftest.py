import os
import tempfile
import uuid
import asyncio

# Must run before app.config / app.database import, otherwise Settings() and
# the engine bind to the developer's real ./data/app.db.
os.environ["DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{os.path.join(tempfile.gettempdir(), f'test_ch_{uuid.uuid4().hex}.db')}"
)

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _search_settings(monkeypatch):
    """Search code sleeps between queries to avoid engine bans; tests must not wait.

    Also snapshot search_max_pages and fetch_concurrency so tests may assign
    them directly and monkeypatch restores the original values on teardown.
    """
    monkeypatch.setattr(settings, "search_delay_between_queries", 0.0)
    monkeypatch.setattr(settings, "search_max_pages", settings.search_max_pages)
    monkeypatch.setattr(settings, "fetch_concurrency", settings.fetch_concurrency)


@pytest.fixture(autouse=True)
def _reset_analyzer_runtime():
    from app import analyzer

    analyzer._analysis_slot = asyncio.Semaphore(1)
    analyzer._progress_store.clear()
    yield
    analyzer._analysis_slot = asyncio.Semaphore(1)
    analyzer._progress_store.clear()
