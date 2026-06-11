"""Application use cases.

They make up the internal API consumed by the input adapters (REST,
scheduler). They coordinate the workflow and repositories without holding
domain logic.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.core.metrics import metrics
from app.domain.entities import WorkflowReport
from app.domain.value_objects import Category
from app.interfaces.publisher import Publisher
from app.interfaces.repositories import JobRepository, StatsSnapshot, StoredJobOffer
from app.workflows.base import JobsWorkflow

logger = get_logger(__name__)


class RunDailyWorkflowUseCase:
    """Runs the daily jobs workflow."""

    def __init__(self, workflow: JobsWorkflow) -> None:
        self._workflow = workflow

    async def execute(self) -> WorkflowReport:
        logger.info("usecase.run_workflow.start")
        return await self._workflow.run()


class ListJobsUseCase:
    """Lists the history of published offers."""

    def __init__(self, repository: JobRepository) -> None:
        self._repo = repository

    async def execute(
        self, *, limit: int, offset: int, category: Category | None
    ) -> list[StoredJobOffer]:
        return await self._repo.list_offers(limit=limit, offset=offset, category=category)


class GetJobUseCase:
    """Retrieves a job offer by id."""

    def __init__(self, repository: JobRepository) -> None:
        self._repo = repository

    async def execute(self, offer_id: int) -> StoredJobOffer | None:
        return await self._repo.get_offer(offer_id)


class GetStatsUseCase:
    """Returns the admin statistics by combining repo + metrics."""

    def __init__(self, repository: JobRepository) -> None:
        self._repo = repository

    async def execute(self) -> StatsSnapshot:
        snapshot = await self._repo.stats()
        run = metrics.snapshot()
        return StatsSnapshot(
            analyzed=snapshot.analyzed,
            published=snapshot.published,
            discarded=snapshot.discarded,
            by_category=snapshot.by_category,
            last_run_at=run["last_run_at"],  # type: ignore[arg-type]
            last_run_status=run["last_run_status"],  # type: ignore[arg-type]
        )


class SendTestMessageUseCase:
    """Publishes a test message to Discord."""

    def __init__(self, publisher: Publisher) -> None:
        self._publisher = publisher

    async def execute(self, text: str) -> int:
        return await self._publisher.publish_test_message(text)
