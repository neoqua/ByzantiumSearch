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
        default_factory=lambda: int(os.getenv("SEARCH_MAX_PAGES", "6"))
    )
    openserp_results_limit: int = field(
        default_factory=lambda: int(os.getenv("OPENSERP_RESULTS_LIMIT", "30"))
    )


settings = Settings()
