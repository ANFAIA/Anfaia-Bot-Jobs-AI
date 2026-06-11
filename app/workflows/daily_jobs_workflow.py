"""Sequential implementation of the daily jobs workflow.

Pipeline:

    Collect Offers → Classify → Rank → Remove Duplicates
    → Edit Job Post → Publish to Discord → Save History
    (repeated until `max_offers_per_run` offers are published)

It is a custom implementation (without an orchestration framework) that honors
the `JobsWorkflow` contract. Each step delegates to a specialized agent. Unlike
a news digest, a jobs channel benefits from several posts per run, so the
pipeline walks the ranked candidates and publishes the top N unique offers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agents.discord_publisher_agent import DiscordPublisherAgent
from app.agents.duplicate_detector import DuplicateDetectorAgent
from app.agents.job_classifier import JobClassifierAgent
from app.agents.job_collector import JobCollectorAgent
from app.agents.job_editor import JobEditorAgent
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.domain.entities import PublishableJobOffer, WorkflowReport
from app.interfaces.repositories import JobRepository
from app.workflows.base import JobsWorkflow

logger = get_logger(__name__)


class DailyJobsWorkflow(JobsWorkflow):
    """Sequential orchestrator of the five agents."""

    def __init__(
        self,
        *,
        collector: JobCollectorAgent,
        classifier: JobClassifierAgent,
        duplicate_detector: DuplicateDetectorAgent,
        editor: JobEditorAgent,
        publisher: DiscordPublisherAgent,
        repository: JobRepository,
        min_relevance_score: int,
        max_offers_per_run: int,
    ) -> None:
        self._collector = collector
        self._classifier = classifier
        self._duplicate_detector = duplicate_detector
        self._editor = editor
        self._publisher = publisher
        self._repo = repository
        self._min_relevance = min_relevance_score
        self._max_offers = max_offers_per_run

    async def run(self) -> WorkflowReport:
        report = WorkflowReport(started_at=datetime.now(UTC))
        try:
            await self._run_pipeline(report)
        except Exception as exc:
            logger.exception("workflow.failed")
            report.errors.append(str(exc))
        finally:
            report.finished_at = datetime.now(UTC)
            status = "success" if report.succeeded else "failed"
            metrics.record_run(status, report.finished_at)
            metrics.increment(f"workflow_runs_{status}")
            logger.info(
                "workflow.finished",
                status=status,
                collected=report.collected,
                published=report.published,
                discarded_duplicates=report.discarded_duplicates,
                discarded_low_relevance=report.discarded_low_relevance,
            )
        return report

    async def _run_pipeline(self, report: WorkflowReport) -> None:
        # 1. Collect.
        collected = await self._collector.run(None)
        report.collected = len(collected)
        metrics.increment("offers_collected", len(collected))
        await self._repo.increment_counter("analyzed", len(collected))
        if not collected:
            report.errors.append("No se recolectó ninguna oferta")
            return

        # 2. Classify (in parallel).
        classified = await asyncio.gather(*(self._classifier.run(offer) for offer in collected))
        report.classified = len(classified)

        # 3. Rank + filter by minimum relevance.
        ranked = sorted(
            classified,
            key=lambda it: it.relevance_score.value if it.relevance_score else 0,
            reverse=True,
        )
        candidates = [
            it
            for it in ranked
            if it.relevance_score and it.relevance_score.is_at_least(self._min_relevance)
        ]
        report.discarded_low_relevance = len(ranked) - len(candidates)
        if not candidates:
            report.errors.append("Ninguna oferta superó el umbral de relevancia")
            return

        # 4-7. Walk the ranked candidates: dedup, edit, publish, persist; stop
        # once the per-run cap is reached. One failing offer does not block the
        # rest of the batch.
        for candidate in candidates:
            if report.published >= self._max_offers:
                break

            decision = await self._duplicate_detector.run(candidate)
            if decision.is_duplicate:
                report.discarded_duplicates += 1
                continue

            try:
                edited = await self._editor.run(candidate)
                post = PublishableJobOffer(offer=candidate, edited=edited)
                published = await self._publisher.run(post)
                offer_id = await self._repo.save_published(published, decision.embedding)
            except Exception as exc:
                logger.exception("workflow.offer_failed", title=candidate.title)
                report.errors.append(f"{candidate.title}: {exc}")
                continue

            await self._repo.increment_counter("published", 1)
            metrics.increment("offers_published")
            report.published += 1
            report.published_offers.append(published)
            logger.info("workflow.published", offer_id=offer_id, title=edited.title)

        await self._repo.increment_counter(
            "discarded", report.discarded_duplicates + report.discarded_low_relevance
        )
        if report.published == 0 and not report.errors:
            report.errors.append("Todas las ofertas candidatas eran duplicadas")
