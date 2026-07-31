import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, init_db
from app.models import Task
from app.schemas import SearchRequest
from app.analyzer import run_analysis, get_progress
from app.report import build_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Cultural History Analyzer", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/api/search")
async def api_search(
    body: SearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        object_name=body.object_name,
        keywords=body.keywords,
        annual_visitors=body.annual_visitors,
        manual_urls=body.manual_urls,
        status="pending",
    )
    db.add(task)
    await db.commit()

    background_tasks.add_task(
        run_analysis,
        task.id,
        body.object_name,
        body.keywords,
        body.manual_urls,
    )

    return {"task_id": task.id, "status": "pending"}


@app.get("/api/tasks/{task_id}/progress")
async def task_progress(task_id: str):
    progress = get_progress(task_id)

    async def event_stream():
        while True:
            progress = get_progress(task_id)
            if progress is None:
                yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                break
            status = progress["status"]
            if status == "completed":
                yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'redirect': f'/results/{task_id}'})}\n\n"
                break
            if status != "processing":
                yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'status': status})}\n\n"
                break

            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"
            await asyncio.sleep(1)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
