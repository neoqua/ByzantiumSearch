from pydantic import BaseModel, Field
from typing import Optional, List, Literal

from app.config import settings


class LLMSettings(BaseModel):
    provider: Literal["local", "yandex", "openai"] = "local"
    endpoint: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    folder_id: Optional[str] = None
    version: Optional[str] = "latest"


class SearchRequest(BaseModel):
    object_name: str
    keywords: str
    annual_visitors: Optional[int] = None
    manual_urls: Optional[str] = None
    llm_settings: Optional[LLMSettings] = None
    search_engine: Literal["searxng", "openserp"] = Field(
        default_factory=lambda: settings.default_search_engine
    )
    content_scope: Literal["personal", "all"] = "personal"
    period_years: int = Field(default=1, ge=0, le=10)


class TaskStatus(BaseModel):
    task_id: str
    status: str
    processed: int = 0
    total: int = 0
    found_keyword: int = 0
    current_url: Optional[str] = None
    current_title: Optional[str] = None
    error_message: Optional[str] = None
    source_mix: Optional[dict] = None
    redirect: Optional[str] = None


class AnalysisResult(BaseModel):
    url: str
    title: Optional[str] = None
    mentions_object: bool = False
    has_keyword: bool = False
    keyword_found: Optional[str] = None
    date_mentioned: Optional[str] = None
    publication_date: Optional[str] = None
    author_location: Optional[str] = None
    source_type: Optional[str] = None
    source_type_label: Optional[str] = None
    analysis_status: str = "ok"
    date_source: Optional[str] = None
    content_kind: Optional[str] = None
    content_kind_label: Optional[str] = None
    relevance_score: float = 0.0


class ReportData(BaseModel):
    task_id: str
    object_name: str
    keywords: str
    annual_visitors: Optional[int]
    urls_processed: int = 0
    total_mentions: int
    mentions_with_keyword: int
    keyword_percentage: float
    percentage_of_visitors: Optional[float] = None
    fetch_failed_count: int = 0
    llm_failed_count: int = 0
    prefiltered_count: int = 0
    disputed_count: int = 0
    analyzed_count: int = 0
    out_of_period_count: int = 0
    not_personal_count: int = 0
    undated_count: int = 0
    content_scope: str = "all"
    period_years: Optional[int] = None
    period_label: str = "без ограничения"
    results: List[AnalysisResult]
    status: str = "completed"
    search_engine: str = "searxng"
    search_engine_label: str = "searxng"
    error_message: Optional[str] = None
    source_mix: Optional[dict] = None
    source_mix_label: str = ""
