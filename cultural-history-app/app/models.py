import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def generate_uuid():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    object_name = Column(String, nullable=False)
    keywords = Column(String, nullable=False)
    annual_visitors = Column(Integer, nullable=True)
    manual_urls = Column(Text, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
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
    relevance_score = Column(Float, default=0.0)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="results")


class UrlCache(Base):
    __tablename__ = "url_cache"

    url = Column(String, primary_key=True)
    object_name = Column(String, nullable=False)
    keywords = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    raw_text_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
