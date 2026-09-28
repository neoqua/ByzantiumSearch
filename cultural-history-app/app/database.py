from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_results_source_type)
        await conn.run_sync(_ensure_tasks_search_engine)
        await conn.run_sync(_ensure_results_analysis_status)
        await conn.run_sync(_ensure_tasks_error_message)
        await conn.run_sync(_ensure_tasks_search_engine_used)
        await conn.run_sync(_ensure_tasks_progress_json)
        await conn.run_sync(_ensure_tasks_stop_requested)
        await conn.run_sync(_ensure_results_date_source)


def _ensure_column(sync_conn, table, column, ddl):
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        sync_conn.execute(text(ddl))


def _ensure_results_source_type(sync_conn):
    _ensure_column(sync_conn, "results", "source_type",
                   "ALTER TABLE results ADD COLUMN source_type VARCHAR(20)")


def _ensure_tasks_search_engine(sync_conn):
    _ensure_column(sync_conn, "tasks", "search_engine",
                   "ALTER TABLE tasks ADD COLUMN search_engine VARCHAR(10) DEFAULT 'searxng'")


def _ensure_results_analysis_status(sync_conn):
    _ensure_column(sync_conn, "results", "analysis_status",
                   "ALTER TABLE results ADD COLUMN analysis_status VARCHAR(20) DEFAULT 'ok'")


def _ensure_tasks_error_message(sync_conn):
    _ensure_column(sync_conn, "tasks", "error_message",
                   "ALTER TABLE tasks ADD COLUMN error_message TEXT")


def _ensure_tasks_search_engine_used(sync_conn):
    _ensure_column(sync_conn, "tasks", "search_engine_used",
                   "ALTER TABLE tasks ADD COLUMN search_engine_used VARCHAR(20)")


def _ensure_tasks_progress_json(sync_conn):
    _ensure_column(sync_conn, "tasks", "progress_json",
                   "ALTER TABLE tasks ADD COLUMN progress_json TEXT")


def _ensure_tasks_stop_requested(sync_conn):
    _ensure_column(sync_conn, "tasks", "stop_requested",
                   "ALTER TABLE tasks ADD COLUMN stop_requested BOOLEAN DEFAULT 0")


def _ensure_results_date_source(sync_conn):
    _ensure_column(sync_conn, "results", "date_source",
                   "ALTER TABLE results ADD COLUMN date_source VARCHAR(10)")
