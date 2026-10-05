import csv
import io
import json
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Task, Result
from app.schemas import ReportData, AnalysisResult
from app.source_type import format_source_mix
from app.fields import format_source_type, format_content_kind, period_label


_DATE_SOURCE_LABEL = {
    "page": "со страницы",
    "llm": "из модели",
}

_STATUS_CSV = {
    "ok": "ок",
    "fetch_failed": "не скачано",
    "llm_failed": "LLM не ответил",
    "prefiltered": "без объекта и ключа",
    "disputed": "спорное упоминание",
    "out_of_period": "вне периода",
    "not_personal": "не личный отзыв",
    "undated": "дата неизвестна",
}

_COUNTED_STATUSES = frozenset({"ok", "prefiltered", "disputed"})


def format_date_source(source: Optional[str]) -> str:
    return _DATE_SOURCE_LABEL.get(source or "", "")


def format_search_engine(requested: Optional[str], used: Optional[str]) -> str:
    requested = requested or "searxng"
    used = used or requested
    if requested == "searxng" and used == "openserp":
        return "searxng → openserp"
    return used


def _source_mix_from_task(task) -> Optional[dict]:
    raw = getattr(task, "progress_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    mix = parsed.get("source_mix")
    return mix if isinstance(mix, dict) else None


async def build_report(task_id: str, session: AsyncSession) -> Optional[ReportData]:
    task = await session.get(Task, task_id)
    if not task:
        return None

    stmt = select(Result).where(Result.task_id == task_id)
    result_rows = (await session.execute(stmt)).scalars().all()

    urls_processed = len(result_rows)
    fetch_failed = sum(1 for r in result_rows if (r.analysis_status or "ok") == "fetch_failed")
    llm_failed = sum(1 for r in result_rows if (r.analysis_status or "ok") == "llm_failed")
    prefiltered = sum(1 for r in result_rows if (r.analysis_status or "ok") == "prefiltered")
    disputed = sum(1 for r in result_rows if (r.analysis_status or "ok") == "disputed")
    out_of_period = sum(1 for r in result_rows if (r.analysis_status or "ok") == "out_of_period")
    not_personal = sum(1 for r in result_rows if (r.analysis_status or "ok") == "not_personal")
    undated = sum(1 for r in result_rows if (r.analysis_status or "ok") == "undated")
    analyzed_count = sum(
        1 for r in result_rows if (r.analysis_status or "ok") in _COUNTED_STATUSES
    )
    ok_rows = [r for r in result_rows if (r.analysis_status or "ok") == "ok"]
    mention_rows = [r for r in ok_rows if r.mentions_object]
    total_mentions = len(mention_rows)
    with_keyword = sum(1 for r in mention_rows if r.has_keyword)
    keyword_pct = round((with_keyword / total_mentions * 100), 1) if total_mentions > 0 else 0.0

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
            source_type_label=format_source_type(r.source_type),
            analysis_status=r.analysis_status or "ok",
            date_source=getattr(r, "date_source", None),
            content_kind=getattr(r, "content_kind", None),
            content_kind_label=format_content_kind(getattr(r, "content_kind", None) or ""),
            excerpt=getattr(r, "excerpt", None),
            impression=getattr(r, "impression", None),
        )
        for r in result_rows
    ]

    requested = task.search_engine
    used = getattr(task, "search_engine_used", None) or requested
    mix = _source_mix_from_task(task)

    return ReportData(
        task_id=task_id,
        object_name=task.object_name,
        keywords=task.keywords,
        annual_visitors=task.annual_visitors,
        urls_processed=urls_processed,
        total_mentions=total_mentions,
        mentions_with_keyword=with_keyword,
        keyword_percentage=keyword_pct,
        percentage_of_visitors=None,
        fetch_failed_count=fetch_failed,
        llm_failed_count=llm_failed,
        prefiltered_count=prefiltered,
        disputed_count=disputed,
        analyzed_count=analyzed_count,
        out_of_period_count=out_of_period,
        not_personal_count=not_personal,
        undated_count=undated,
        content_scope=getattr(task, "content_scope", None) or "all",
        period_years=getattr(task, "period_years", None),
        period_label=period_label(getattr(task, "period_years", None)),
        results=results_list,
        status=task.status,
        search_engine=requested,
        search_engine_label=format_search_engine(requested, used),
        error_message=getattr(task, "error_message", None),
        source_mix=mix,
        source_mix_label=format_source_mix(mix),
    )


def report_to_csv(report: ReportData) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([
        "№", "URL", "Заголовок", "Цитата", "Смысл", "Источник", "Тип текста",
        "Ключевые слова", "Дата публикации", "Источник даты публикации",
        "Дата упоминания", "Геопривязка", "Релевантность", "Упоминает объект", "Статус",
    ])
    for i, r in enumerate(report.results, 1):
        mentions_val = "да" if r.mentions_object else "нет"
        status_val = _STATUS_CSV.get(r.analysis_status or "ok", r.analysis_status or "ok")
        writer.writerow([
            i,
            r.url,
            r.title or "",
            r.excerpt or "",
            r.impression or "",
            r.source_type_label or r.source_type or "",
            r.content_kind_label or r.content_kind or "",
            r.keyword_found or "",
            r.publication_date or "",
            format_date_source(r.date_source),
            r.date_mentioned or "",
            r.author_location or "",
            r.relevance_score,
            mentions_val,
            status_val,
        ])
    return "\ufeff" + buf.getvalue()
