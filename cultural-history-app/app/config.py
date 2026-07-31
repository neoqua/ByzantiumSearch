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


settings = Settings()
