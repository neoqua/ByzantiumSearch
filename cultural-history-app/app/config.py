import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./data/app.db"
        )
    )
    searxng_base_url: str = field(
        default_factory=lambda: os.getenv("SEARXNG_BASE_URL", "http://localhost:8888")
    )
    lm_studio_base_url: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234")
    )
    lm_studio_model: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_MODEL", "meta-llama-3.1-8b-instruct")
    )
    openserp_base_url: str = field(
        default_factory=lambda: os.getenv("OPENSERP_BASE_URL", "http://localhost:7000")
    )
    openserp_engines: str = field(
        default_factory=lambda: os.getenv("OPENSERP_ENGINES", "google,yandex,duckduckgo")
    )
    openserp_mode: str = field(
        default_factory=lambda: os.getenv("OPENSERP_MODE", "balanced")
    )
    search_max_pages: int = field(
        default_factory=lambda: int(os.getenv("SEARCH_MAX_PAGES", "3"))
    )
    search_delay_between_queries: float = field(
        default_factory=lambda: float(os.getenv("SEARCH_DELAY", "1.5"))
    )
    openserp_results_limit: int = field(
        default_factory=lambda: int(os.getenv("OPENSERP_RESULTS_LIMIT", "30"))
    )
    default_search_engine: str = field(
        default_factory=lambda: _read_search_engine(
            os.getenv("DEFAULT_SEARCH_ENGINE", "openserp")
        )
    )
    scraper_verify_ssl: bool = field(
        default_factory=lambda: _read_bool(os.getenv("SCRAPER_VERIFY_SSL"), False)
    )
    llm_text_limit: int = field(
        default_factory=lambda: max(1, int(os.getenv("LLM_TEXT_LIMIT", "3000")))
    )
    fetch_concurrency: int = field(
        default_factory=lambda: max(1, int(os.getenv("FETCH_CONCURRENCY", "3")))
    )


SEARCH_ENGINES = ("searxng", "openserp")


def _read_search_engine(value):
    value = (value or "").strip().lower()
    return value if value in SEARCH_ENGINES else "openserp"


def _read_bool(value, default):
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


settings = Settings()
