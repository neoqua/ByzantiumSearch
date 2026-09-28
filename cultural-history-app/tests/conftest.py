import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _search_settings(monkeypatch):
    """Search code sleeps between queries to avoid engine bans; tests must not wait.

    Also snapshot search_max_pages so tests may assign it directly and
    monkeypatch restores the original value on teardown.
    """
    monkeypatch.setattr(settings, "search_delay_between_queries", 0.0)
    monkeypatch.setattr(settings, "search_max_pages", settings.search_max_pages)
