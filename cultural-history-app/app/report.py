import csv
import io
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Task, Result
from app.schemas import ReportData, AnalysisResult


_STATUS_CSV = {
    "ok": "ок",
    "fetch_failed": "не скачано",
    "llm_failed": "LLM не ответил",
}


def format_search_engine(requested: Optional[str], used: Optional[str]) -> str:
    requested = requested or "searxng"
    used = used or requested
    if requested == "searxng" and used == "openserp":
        return "searxng → openserp"
    return used


async def build_report(task_id: str, session: AsyncSession) -> Optional[ReportData]:
    task = await session.get(Task, task_id)
    if not task:
        return None

    stmt = select(Result).where(Result.task_id == task_id)
    result_rows = (await session.execute(stmt)).scalars().all()

    urls_processed = len(result_rows)
    fetch_failed = sum(1 for r in result_rows if (r.analysis_status or "ok") == "fetch_failed")
    llm_failed = sum(1 for r in result_rows if (r.analysis_status or "ok") == "llm_failed")
    ok_rows = [r for r in result_rows if (r.analysis_status or "ok") == "ok"]
    total_mentions = sum(1 for r in ok_rows if r.mentions_object)
    with_keyword = sum(1 for r in ok_rows if r.has_keyword)
    ok_count = len(ok_rows)
    keyword_pct = round((with_keyword / ok_count * 100), 1) if ok_count > 0 else 0.0

    visitor_pct = None
    if task.annual_visitors and task.annual_visitors > 0:
        visitor_pct = round((with_keyword / task.annual_visitors * 100), 4)

    results_list = [
        AnalysisResult(
            url=r.url,
            title=r.title,
            mentions_object=r.mentions_object,
            has_keyword=r.has_keyword,
            keyword_found=r.keyword_found,
            date_mentioned=r.date_mentioned,
            publication_date=r.publication_date,
            author_location=r.author_location,
            relevance_score=r.relevance_score or 0.0,
            source_type=r.source_type,
            analysis_status=r.analysis_status or "ok",
        )
        for r in result_rows
    ]

    requested = task.search_engine
    used = getattr(task, "search_engine_used", None) or requested

    return ReportData(
        task_id=task_id,
        object_name=task.object_name,
        keywords=task.keywords,
        annual_visitors=task.annual_visitors,
        urls_processed=urls_processed,
        total_mentions=total_mentions,
        mentions_with_keyword=with_keyword,
        keyword_percentage=keyword_pct,
        percentage_of_visitors=visitor_pct,
        fetch_failed_count=fetch_failed,
        llm_failed_count=llm_failed,
        results=results_list,
        status=task.status,
        search_engine=requested,
        search_engine_label=format_search_engine(requested, used),
        error_message=getattr(task, "error_message", None),
    )


def report_to_csv(report: ReportData) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([
        "№", "URL", "Заголовок", "Источник", "Ключевые слова",
        "Дата", "Геопривязка", "Релевантность", "Упоминает объект", "Статус",
    ])
    for i, r in enumerate(report.results, 1):
        date_val = r.publication_date or r.date_mentioned or ""
        mentions_val = "да" if r.mentions_object else "нет"
        status_val = _STATUS_CSV.get(r.analysis_status or "ok", r.analysis_status or "ok")
        writer.writerow([
            i,
            r.url,
            r.title or "",
            r.source_type or "",
            r.keyword_found or "",
            date_val,
            r.author_location or "",
            r.relevance_score,
            mentions_val,
            status_val,
        ])
    return "\ufeff" + buf.getvalue()
