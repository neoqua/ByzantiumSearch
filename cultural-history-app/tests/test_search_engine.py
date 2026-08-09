from app.config import settings
from app.schemas import SearchRequest, ReportData


def test_search_request_defaults_to_searxng():
    r = SearchRequest(object_name="X", keywords="k")
    assert r.search_engine == "searxng"


def test_search_request_accepts_openserp():
    r = SearchRequest(object_name="X", keywords="k", search_engine="openserp")
    assert r.search_engine == "openserp"


def test_report_data_has_search_engine_default():
    r = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        total_mentions=0, mentions_with_keyword=0, keyword_percentage=0.0,
        percentage_of_visitors=None, results=[],
    )
    assert r.search_engine == "searxng"


def test_config_openserp_defaults():
    assert settings.openserp_base_url == "http://localhost:7000"
    assert settings.openserp_engines == "google,yandex,duckduckgo"
    assert settings.openserp_mode == "balanced"
    assert settings.search_max_pages == 1
    assert settings.openserp_results_limit == 30
