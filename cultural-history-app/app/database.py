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
