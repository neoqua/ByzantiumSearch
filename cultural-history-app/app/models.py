import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    object_name = Column(String, nullable=False)
    keywords = Column(String, nullable=False)
    annual_visitors = Column(Integer, nullable=True)
    manual_urls = Column(Text, nullable=True)
    search_engine = Column(String, nullable=False, default="searxng")
    search_engine_used = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    progress_json = Column(Text, nullable=True)
    stop_requested = Column(Boolean, default=False)
    content_scope = Column(String, nullable=True)
    period_years = Column(Integer, nullable=True)
    period_cutoff = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    results = relationship("Result", back_populates="task", cascade="all, delete-orphan")


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=True)
    mentions_object = Column(Boolean, default=False)
    has_keyword = Column(Boolean, default=False)
    keyword_found = Column(String, nullable=True)
    date_mentioned = Column(String, nullable=True)
    publication_date = Column(String, nullable=True)
    author_location = Column(String, nullable=True)
    source_type = Column(String, nullable=True)
    analysis_status = Column(String, nullable=False, default="ok")
    date_source = Column(String, nullable=True)
    content_kind = Column(String, nullable=True)
    excerpt = Column(Text, nullable=True)
    impression = Column(Text, nullable=True)
    relevance_score = Column(Float, default=0.0)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    task = relationship("Task", back_populates="results")


class UrlCache(Base):
    """Legacy single-URL cache. Kept so existing SQLite files still load."""

    __tablename__ = "url_cache"

    url = Column(String, primary_key=True)
    object_name = Column(String, nullable=False)
    keywords = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class UrlCacheV2(Base):
    """Cache keyed by URL + object + keywords so objects do not share rows."""

    __tablename__ = "url_cache_v2"

    url = Column(String, primary_key=True)
    object_name = Column(String, primary_key=True)
    keywords = Column(String, primary_key=True)
    result_json = Column(Text, nullable=True)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
