from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .models import ActorProfile


@dataclass(frozen=True)
class Settings:
    imap_host: str
    imap_port: int
    imap_username: str
    imap_password: str
    imap_folder: str
    email_search_query: str
    email_subject_keywords: list[str]
    openai_api_key: str | None
    llm_model: str
    max_llm_calls_per_scan: int
    min_match_score: float
    actor_profile_path: Path
    database_path: Path
    dry_run: bool
    ai_builder_api_key: str | None = None
    ai_builder_base_url: str = "https://space.ai-builders.com/backend/v1"
    reviewer_model: str = "deepseek-v4-pro"
    max_reviewer_calls_per_scan: int = 20


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        imap_host=_required("IMAP_HOST"),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        imap_username=_required("IMAP_USERNAME"),
        imap_password=_required("IMAP_PASSWORD"),
        imap_folder=os.getenv("IMAP_FOLDER", "INBOX"),
        email_search_query=os.getenv("EMAIL_SEARCH_QUERY", '(FROM "backstage")'),
        email_subject_keywords=_list_env("EMAIL_SUBJECT_KEYWORDS", "basic filter"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        max_llm_calls_per_scan=int(os.getenv("MAX_LLM_CALLS_PER_SCAN", "20")),
        ai_builder_api_key=os.getenv("AI_BUILDER_API_KEY") or None,
        ai_builder_base_url=os.getenv(
            "AI_BUILDER_BASE_URL",
            "https://space.ai-builders.com/backend/v1",
        ),
        reviewer_model=os.getenv("REVIEWER_MODEL", "deepseek-v4-pro"),
        max_reviewer_calls_per_scan=int(os.getenv("MAX_REVIEWER_CALLS_PER_SCAN", "20")),
        min_match_score=float(os.getenv("MIN_MATCH_SCORE", "0.72")),
        actor_profile_path=Path(os.getenv("ACTOR_PROFILE_PATH", "profile.example.json")),
        database_path=Path(os.getenv("DATABASE_PATH", "backstage_agent.sqlite3")),
        dry_run=_truthy(os.getenv("DRY_RUN", "true")),
    )


def load_actor_profile(path: Path) -> ActorProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ActorProfile(**data)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _list_env(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]
