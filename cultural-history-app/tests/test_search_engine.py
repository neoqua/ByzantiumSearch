from app.config import settings, _read_search_engine
from app.schemas import SearchRequest, ReportData


def test_search_request_defaults_to_configured_engine():
    r = SearchRequest(object_name="X", keywords="k")
    assert r.search_engine == settings.default_search_engine


def test_search_request_default_follows_settings(monkeypatch):
    monkeypatch.setattr(settings, "default_search_engine", "searxng")
    assert SearchRequest(object_name="X", keywords="k").search_engine == "searxng"
    monkeypatch.setattr(settings, "default_search_engine", "openserp")
    assert SearchRequest(object_name="X", keywords="k").search_engine == "openserp"


def test_search_request_accepts_both_engines():
    assert SearchRequest(object_name="X", keywords="k", search_engine="openserp").search_engine == "openserp"
    assert SearchRequest(object_name="X", keywords="k", search_engine="searxng").search_engine == "searxng"


def test_read_search_engine_falls_back_on_garbage():
    assert _read_search_engine("searxng") == "searxng"
    assert _read_search_engine(" OpenSERP ") == "openserp"
    assert _read_search_engine("bing") == "openserp"
    assert _read_search_engine(None) == "openserp"


def test_report_data_has_search_engine_default():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[],
    )
    assert r.search_engine == "searxng"  # legacy rows created before the column existed


def test_config_search_defaults():
    assert settings.openserp_base_url == "http://localhost:7000"
    assert settings.openserp_engines == "google,yandex,duckduckgo"
    assert settings.openserp_mode == "balanced"
    assert settings.search_max_pages == 3
    assert settings.openserp_results_limit == 30
    assert settings.default_search_engine == "openserp"
