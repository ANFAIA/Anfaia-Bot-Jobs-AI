"""Dependency injection container (composition root).

This is the only place where concrete adapters are wired up with the business
logic. It builds the object graph from the configuration and exposes it to the
inbound adapters (API and scheduler). Keeping it here lets us swap any
implementation (LLM, source, repository, publisher) without touching the rest.
"""

from __future__ import annotations

import httpx

from app.agents import (
    DiscordPublisherAgent,
    DuplicateDetectorAgent,
    JobClassifierAgent,
    JobCollectorAgent,
    JobEditorAgent,
)
from app.application.use_cases import (
    GetJobUseCase,
    GetStatsUseCase,
    ListJobsUseCase,
    RunDailyWorkflowUseCase,
    SendTestMessageUseCase,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.database.repositories import SqlAlchemyJobRepository
from app.database.session import Database
from app.infrastructure.discord.discord_publisher import DiscordPublisher
from app.infrastructure.discord.null_publisher import NullPublisher
from app.infrastructure.embeddings.factory import build_embedding_provider
from app.infrastructure.llm.factory import build_llm_provider
from app.infrastructure.sources.registry import build_default_sources
from app.interfaces.publisher import Publisher
from app.interfaces.repositories import JobRepository
from app.workflows.base import JobsWorkflow
from app.workflows.daily_jobs_workflow import DailyJobsWorkflow

logger = get_logger(__name__)


class Container:
    """Process dependency graph, built only once at startup."""

    def __init__(self, settings: Settings, *, repository: JobRepository | None = None) -> None:
        self.settings = settings

        # --- Shared HTTP client ---
        self.http_client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        )

        # --- Persistence ---
        self.database: Database | None = None
        if repository is not None:
            self.repository = repository
        else:
            self.database = Database(settings.database_url, echo=False)
            self.repository = SqlAlchemyJobRepository(self.database)

        # --- Outbound adapters ---
        self.llm = build_llm_provider(settings, self.http_client)
        self.embeddings = build_embedding_provider(settings, self.http_client)
        self.publisher: Publisher = self._build_publisher(settings)
        self.sources = build_default_sources(
            self.http_client,
            remotive_enabled=settings.remotive_enabled,
            remotive_category=settings.remotive_category,
            remoteok_enabled=settings.remoteok_enabled,
            arbeitnow_enabled=settings.arbeitnow_enabled,
            rss_feeds=settings.job_rss_feed_list,
        )

        # --- Agents ---
        self.collector_agent = JobCollectorAgent(
            self.sources,
            max_items_per_source=settings.max_items_per_source,
            keywords=settings.job_keyword_list,
        )
        self.classifier_agent = JobClassifierAgent(self.llm)
        self.duplicate_agent = DuplicateDetectorAgent(
            self.repository,
            self.embeddings,
            similarity_threshold=settings.duplicate_similarity_threshold,
        )
        self.editor_agent = JobEditorAgent(self.llm)
        self.publisher_agent = DiscordPublisherAgent(self.publisher)

        # --- Workflow ---
        self.workflow: JobsWorkflow = DailyJobsWorkflow(
            collector=self.collector_agent,
            classifier=self.classifier_agent,
            duplicate_detector=self.duplicate_agent,
            editor=self.editor_agent,
            publisher=self.publisher_agent,
            repository=self.repository,
            min_relevance_score=settings.min_relevance_score,
            max_offers_per_run=settings.max_offers_per_run,
            europe_boost=settings.europe_boost,
            spain_offers_per_run=settings.spain_offers_per_run,
        )

        # --- Use cases ---
        self.run_workflow_uc = RunDailyWorkflowUseCase(self.workflow)
        self.list_jobs_uc = ListJobsUseCase(self.repository)
        self.get_job_uc = GetJobUseCase(self.repository)
        self.stats_uc = GetStatsUseCase(self.repository)
        self.test_discord_uc = SendTestMessageUseCase(self.publisher)

    @staticmethod
    def _build_publisher(settings: Settings) -> Publisher:
        if settings.discord_token and settings.discord_channel_id:
            return DiscordPublisher(settings.discord_token, settings.discord_channel_id)
        logger.warning("container.discord_not_configured")
        return NullPublisher()

    async def aclose(self) -> None:
        """Release resources (HTTP client and database connections)."""
        await self.http_client.aclose()
        if self.database is not None:
            await self.database.dispose()
