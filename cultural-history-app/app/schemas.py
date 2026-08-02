from pydantic import BaseModel
from typing import Optional, List, Literal


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


class TaskStatus(BaseModel):
    task_id: str
    status: str
    processed: int = 0
    total: int = 0
    found_keyword: int = 0
    current_url: Optional[str] = None
    current_title: Optional[str] = None


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
    relevance_score: float = 0.0


class ReportData(BaseModel):
    task_id: str
    object_name: str
    keywords: str
    annual_visitors: Optional[int]
    total_mentions: int
    mentions_with_keyword: int
    keyword_percentage: float
    percentage_of_visitors: Optional[float]
    results: List[AnalysisResult]
    status: str = "completed"
