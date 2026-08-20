import csv
import io
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Task, Result
from app.schemas import ReportData, AnalysisResult


async def build_report(task_id: str, session: AsyncSession) -> Optional[ReportData]:
    task = await session.get(Task, task_id)
    if not task:
        return None

    stmt = select(Result).where(Result.task_id == task_id)
    result_rows = (await session.execute(stmt)).scalars().all()

    total = len(result_rows)
    with_keyword = sum(1 for r in result_rows if r.has_keyword)
    keyword_pct = round((with_keyword / total * 100), 1) if total > 0 else 0.0

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
        )
        for r in result_rows
    ]

    return ReportData(
        task_id=task_id,
        object_name=task.object_name,
        keywords=task.keywords,
        annual_visitors=task.annual_visitors,
        total_mentions=total,
        mentions_with_keyword=with_keyword,
        keyword_percentage=keyword_pct,
        percentage_of_visitors=visitor_pct,
        results=results_list,
        status=task.status,
        search_engine=task.search_engine,
    )


def report_to_csv(report: ReportData) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([
        "№", "URL", "Заголовок", "Источник", "Ключевые слова",
        "Дата", "Геопривязка", "Релевантность", "Упоминает объект",
    ])
    for i, r in enumerate(report.results, 1):
        date_val = r.publication_date or r.date_mentioned or ""
        mentions_val = "да" if r.mentions_object else "нет"
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
        ])
    return "\ufeff" + buf.getvalue()
