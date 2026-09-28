import asyncio
from app.models import Result
from app.report import build_report, report_to_csv, format_search_engine
from app.schemas import ReportData, AnalysisResult


def _session(task, rows):
    class _Session:
        async def get(self, model, task_id):
            return task

        async def execute(self, stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return rows
                    return _S()
            return _R()
    return _Session()


def _task(**kwargs):
    class _Task:
        object_name = "Объект"
        keywords = "Византия"
        annual_visitors = 10000
        status = "completed"
        search_engine = "searxng"
        search_engine_used = "searxng"
        error_message = None
    t = _Task()
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


def test_format_search_engine_fallback_label():
    assert format_search_engine("searxng", "openserp") == "searxng → openserp"
    assert format_search_engine("openserp", "openserp") == "openserp"
    assert format_search_engine("searxng", "searxng") == "searxng"
    assert format_search_engine("searxng", None) == "searxng"


def test_total_mentions_counts_only_ok_object_hits():
    rows = [
        Result(task_id="t", url="https://a", mentions_object=True, has_keyword=True,
               analysis_status="ok", source_type="blog"),
        Result(task_id="t", url="https://b", mentions_object=False, has_keyword=False,
               analysis_status="ok", source_type="other"),
        Result(task_id="t", url="https://c", mentions_object=False, has_keyword=False,
               analysis_status="fetch_failed", source_type="other"),
        Result(task_id="t", url="https://d", mentions_object=False, has_keyword=True,
               analysis_status="llm_failed", source_type="other"),
    ]
    report = asyncio.run(build_report("t", _session(_task(), rows)))
    assert report.urls_processed == 4
    assert report.total_mentions == 1
    assert report.mentions_with_keyword == 1
    assert report.fetch_failed_count == 1
    assert report.llm_failed_count == 1
    assert report.keyword_percentage == 50.0  # 1 of 2 ok rows
    assert report.percentage_of_visitors == 0.01
    assert report.search_engine_label == "searxng"


def test_report_label_shows_fallback():
    report = asyncio.run(build_report(
        "t",
        _session(_task(search_engine="searxng", search_engine_used="openserp"), []),
    ))
    assert report.search_engine == "searxng"
    assert report.search_engine_label == "searxng → openserp"


def test_failed_task_carries_error_message():
    report = asyncio.run(build_report(
        "t",
        _session(_task(status="failed", error_message="Поиск не вернул ни одного URL"), []),
    ))
    assert report.status == "failed"
    assert "не вернул" in report.error_message


def test_csv_includes_mentions_and_status():
    report = ReportData(
        task_id="t", object_name="o", keywords="k", annual_visitors=None,
        urls_processed=2, total_mentions=1, mentions_with_keyword=1,
        keyword_percentage=100.0, percentage_of_visitors=None,
        fetch_failed_count=1, llm_failed_count=0,
        results=[
            AnalysisResult(url="https://ok", mentions_object=True, analysis_status="ok"),
            AnalysisResult(url="https://bad", mentions_object=False, analysis_status="fetch_failed"),
        ],
    )
    csv_text = report_to_csv(report)
    assert csv_text.startswith("\ufeff")
    assert "Упоминает объект" in csv_text
    assert "Статус" in csv_text
    assert "да" in csv_text
    assert "не скачано" in csv_text
