import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import settings
from app.database import get_db, init_db, async_session
from app.models import Task
from app.schemas import SearchRequest, LLMSettings
from app.fields import period_cutoff, cutoff_iso
from app.analyzer import (
    run_analysis,
    get_progress,
    seed_progress,
    public_progress,
    progress_from_task,
    request_stop,
    fail_interrupted_tasks,
)
from app.report import build_report, report_to_csv
from app.llm_providers import get_provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    n = await fail_interrupted_tasks()
    if n:
        logger.info("Marked %s interrupted task(s) as failed", n)
    yield


app = FastAPI(title="Cultural History Analyzer", lifespan=lifespan)


TASK_STATUS_LABELS = {
    "pending": "ожидание",
    "queued": "в очереди",
    "processing": "выполняется",
    "completed": "готов",
    "stopped": "остановлен",
    "failed": "ошибка",
}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(Task).order_by(Task.created_at.desc()).limit(30)
    recent_tasks = (await db.execute(stmt)).scalars().all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_search_engine": settings.default_search_engine,
            "yandex_folder_id": settings.yandex_folder_id,
            "yandex_endpoint": settings.yandex_endpoint,
            "yandex_model": settings.yandex_model,
            "recent_tasks": recent_tasks,
            "status_labels": TASK_STATUS_LABELS,
        },
    )


@app.post("/api/search")
async def api_search(
    body: SearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    cutoff = period_cutoff(body.period_years)
    task = Task(
        object_name=body.object_name,
        keywords=body.keywords,
        annual_visitors=body.annual_visitors,
        manual_urls=body.manual_urls,
        search_engine=body.search_engine,
        content_scope=body.content_scope,
        period_years=body.period_years or None,
        period_cutoff=cutoff_iso(cutoff),
        status="pending",
    )
    db.add(task)
    await db.commit()

    seed_progress(task.id)

    background_tasks.add_task(
        run_analysis,
        task.id,
        body.object_name,
        body.keywords,
        body.manual_urls,
        body.llm_settings,
        body.search_engine,
    )

    return {"task_id": task.id, "status": "pending"}


@app.post("/api/llm/test")
async def test_llm_connection(body: LLMSettings):
    try:
        provider = get_provider(body)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    try:
        await provider.complete("Say OK")
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "").strip()[:400]
        detail = body or e.response.reason_phrase or str(e)
        return {"ok": False, "error": f"{e.response.status_code}: {detail}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    ok = await request_stop(task_id)
    if not ok:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"status": "stopping"}


_FINAL = frozenset({"completed", "stopped", "failed"})


def _task_status_body(task_id: str, progress: dict, error_message=None) -> dict:
    body = {
        "task_id": task_id,
        **public_progress(progress),
        "error_message": error_message if error_message is not None else progress.get("error_message"),
    }
    if body["status"] in _FINAL:
        body["redirect"] = f"/results/{task_id}"
    return body


@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if task is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    progress = get_progress(task_id) or progress_from_task(task)
    return _task_status_body(task_id, progress, task.error_message)


@app.get("/api/tasks/{task_id}/progress")
async def task_progress(task_id: str, db: AsyncSession = Depends(get_db)):
    if get_progress(task_id) is None:
        task = await db.get(Task, task_id)
        if task is None:
            return JSONResponse({"error": "not found"}, status_code=404)

    async def event_stream():
        while True:
            progress = get_progress(task_id)
            if progress is None:
                async with async_session() as session:
                    task = await session.get(Task, task_id)
                if task is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                    break
                progress = progress_from_task(task)
            status = progress["status"]
            if status in _FINAL:
                yield (
                    "event: done\n"
                    f"data: {json.dumps({'task_id': task_id, 'redirect': f'/results/{task_id}'})}\n\n"
                )
                break
            if status in ("processing", "pending", "queued"):
                yield f"event: progress\ndata: {json.dumps(public_progress(progress))}\n\n"
                await asyncio.sleep(1)
                continue
            yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'status': status})}\n\n"
            break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/tasks/{task_id}/results")
async def task_results(task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return report.model_dump()


@app.get("/results/{task_id}", response_class=HTMLResponse)
async def results_page(request: Request, task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return templates.TemplateResponse(request, "results.html", {"report": None, "error": "Task not found"})
    return templates.TemplateResponse(request, "results.html", {"report": report, "error": None})


@app.get("/results/{task_id}/csv")
async def download_csv(task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    csv_bytes = report_to_csv(report).encode("utf-8")
    return Response(
        csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report_{task_id}.csv"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
