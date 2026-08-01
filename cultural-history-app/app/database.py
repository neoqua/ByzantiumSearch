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


def _ensure_results_source_type(sync_conn):
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    if "results" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("results")}
    if "source_type" not in cols:
        sync_conn.execute(text("ALTER TABLE results ADD COLUMN source_type VARCHAR(20)"))
