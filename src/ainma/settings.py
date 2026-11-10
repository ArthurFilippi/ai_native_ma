"""Runtime configuration, read from the environment and an optional `.env` file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SEED = 1234


class Settings(BaseSettings):
    """Every variable is listed in `.env.example`. Secrets only ever come from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["mock", "gemini", "openai"] = "mock"
    llm_model: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    llm_cache_dir: Path = Path("data/cache/llm")
    llm_max_concurrency: int = 4  # calls in flight per provider object
    llm_timeout_s: float = 60.0
    # a failed live call raises (the API answers 503) unless this is set: then the mock answers
    # and the answer is marked `degraded` (D88). Never on by default.
    llm_allow_mock_fallback: bool = False
    # the judge model, distinct from the writer to avoid self preference; empty: same as writer
    judge_provider: Literal["", "mock", "gemini", "openai"] = ""
    judge_model: str = ""

    embeddings_backend: Literal["lsa", "fastembed"] = "lsa"
    embeddings_model: str = "BAAI/bge-small-en-v1.5"
    reranker_backend: Literal["features", "cross_encoder"] = "features"

    store_backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: Path = Path("data/cache/ainma.sqlite")
    database_url: str = ""

    demo_auth: bool = True
    allowed_origins: str = "http://localhost:3000"
    seed: int = DEFAULT_SEED


def get_settings() -> Settings:
    """Build settings fresh on each call: no module level cache, no global state."""
    return Settings()
