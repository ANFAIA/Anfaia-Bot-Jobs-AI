"""Centralized application configuration (pydantic-settings).

All configuration is loaded from environment variables / the `.env` file.
This is the only point in the system that knows about the environment; the rest
of the code receives its configuration via dependency injection.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


class EmbeddingProviderName(StrEnum):
    OPENAI = "openai"
    HASH = "hash"


def _parse_rss_feeds(raw: str) -> list[tuple[str, str]]:
    """Parse "Name|URL" entries separated by commas or newlines."""
    feeds: list[tuple[str, str]] = []
    for entry in (e.strip() for chunk in raw.split("\n") for e in chunk.split(",")):
        if not entry:
            continue
        name, sep, url = entry.partition("|")
        name, url = name.strip(), url.strip()
        if not sep or not name or not url.startswith(("http://", "https://")):
            raise ValueError(
                f"Entrada RSS inválida: {entry!r}. Formato esperado: 'Nombre|https://...'"
            )
        feeds.append((name, url))
    return feeds


def _validate_hhmm(value: str) -> str:
    """Validate a 24h HH:MM time string."""
    hh, _, mm = value.partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        raise ValueError("La hora debe tener formato HH:MM (24h)")
    return value


class Settings(BaseSettings):
    """Typed and validated system configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ---
    # PostgreSQL connection parts, all read from the environment. They are used
    # to assemble `database_url` when it is not provided explicitly, so there is
    # a single source of truth and no hardcoded credentials.
    postgres_user: str = "anfaia"
    postgres_password: str = "anfaia"
    postgres_db: str = "anfaia_jobs"
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    # Full async DSN. If set in the environment it takes precedence; otherwise it
    # is built from the POSTGRES_* parts above.
    database_url: str | None = None

    # --- LLM ---
    llm_provider: LLMProviderName = LLMProviderName.OPENAI
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None

    # --- Embeddings ---
    embedding_provider: EmbeddingProviderName = EmbeddingProviderName.OPENAI
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    # Job boards cross-post the same offer with rewritten descriptions, so the
    # threshold is a bit higher than for news to avoid false positives between
    # different roles at the same company.
    duplicate_similarity_threshold: float = 0.90

    # --- Discord ---
    discord_token: str | None = None
    discord_channel_id: int | None = None

    # --- Scheduler ---
    scheduler_enabled: bool = True
    post_time: str = "10:00"
    timezone: str = "Europe/Madrid"

    # --- Collection ---
    max_items_per_source: int = 25
    min_relevance_score: int = 55
    max_offers_per_run: int = 3
    # Keyword pre-filter applied by the collector (comma-separated). An offer
    # must match at least one keyword in title/tags/description to enter the
    # pipeline; this keeps LLM calls bounded. Empty disables the filter.
    # Includes Spanish terms so offers from Spanish boards (SEPE, Tecnoempleo)
    # are not dropped before classification.
    job_keywords: str = (
        "ai,machine learning,ml,llm,data,python,deep learning,nlp,mlops,"
        "inteligencia artificial,desarrollador,programador,ingenier,software,datos"
    )

    # --- Prioritization ---
    # Ranking boost (±) applied to offers that can / explicitly cannot be
    # applied to from Europe. Ordering only; the relevance threshold
    # (MIN_RELEVANCE_SCORE) always uses the raw classifier score.
    europe_boost: int = 15
    # Best-effort slots reserved each run for offers based in Spain
    # (0 disables the quota).
    spain_offers_per_run: int = 1
    http_user_agent: str = "AnfaiaJobsAI/0.1 (+https://anfaia.org)"
    http_timeout_seconds: float = 20.0

    # --- Sources ---
    remotive_enabled: bool = True
    remotive_category: str = "software-dev"
    remoteok_enabled: bool = True
    arbeitnow_enabled: bool = True
    # Extra RSS job feeds: "Name|URL" entries separated by commas or newlines.
    # Unset/empty keeps the built-in default catalog (see sources/registry.py).
    job_rss_feeds: str | None = None

    @field_validator(
        "openai_api_key",
        "anthropic_api_key",
        "openrouter_api_key",
        "discord_token",
        "discord_channel_id",
        "job_rss_feeds",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        # An empty value in the .env (e.g. DISCORD_CHANNEL_ID=) means "unset".
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @model_validator(mode="after")
    def _assemble_database_url(self) -> Settings:
        # Build the DSN from the POSTGRES_* parts unless DATABASE_URL was given.
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self

    @field_validator("post_time")
    @classmethod
    def _validate_times(cls, value: str) -> str:
        return _validate_hhmm(value)

    @field_validator("job_rss_feeds")
    @classmethod
    def _validate_job_rss_feeds(cls, value: str | None) -> str | None:
        # Fail fast on malformed entries instead of silently dropping feeds.
        if value is not None:
            _parse_rss_feeds(value)
        return value

    @property
    def job_rss_feed_list(self) -> list[tuple[str, str]] | None:
        """Parsed RSS catalog override, or None to use the built-in defaults."""
        if self.job_rss_feeds is None:
            return None
        return _parse_rss_feeds(self.job_rss_feeds)

    @property
    def job_keyword_list(self) -> list[str]:
        return [kw.strip().lower() for kw in self.job_keywords.split(",") if kw.strip()]

    @property
    def post_hour(self) -> int:
        return int(self.post_time.split(":")[0])

    @property
    def post_minute(self) -> int:
        return int(self.post_time.split(":")[1])

    @property
    def active_llm_api_key(self) -> str | None:
        return {
            LLMProviderName.OPENAI: self.openai_api_key,
            LLMProviderName.ANTHROPIC: self.anthropic_api_key,
            LLMProviderName.OPENROUTER: self.openrouter_api_key,
        }[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of the configuration."""
    return Settings()
