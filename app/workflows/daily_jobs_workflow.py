"""Sequential implementation of the daily jobs workflow.

Pipeline:

    Collect Offers → Classify → Rank (Europe-friendly first) → Remove Duplicates
    → Edit Job Post → Publish to Discord → Save History
    (repeated until `max_offers_per_run` offers are published)

It is a custom implementation (without an orchestration framework) that honors
the `JobsWorkflow` contract. Each step delegates to a specialized agent. Unlike
a news digest, a jobs channel benefits from several posts per run, so the
pipeline walks the ranked candidates and publishes the top N unique offers.

Three community-driven selection rules apply on top of the relevance ranking:
  - Offers applicable from Europe get a ranking boost (and offers explicitly
    restricted to other regions get the same penalty).
  - A best-effort number of slots per run is reserved for offers based in
    Spain (`spain_offers_per_run`), so local offers are not always crowded out
    by the international remote boards.
  - At most one offer per company per run, so a company bulk-posting several
    roles does not monopolize the day's batch.
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
from app.domain.entities import JobOffer, PublishableJobOffer, WorkflowReport
from app.domain.geo import europe_friendly, is_spain_offer
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
        europe_boost: int = 15,
        spain_offers_per_run: int = 1,
    ) -> None:
        self._collector = collector
        self._classifier = classifier
        self._duplicate_detector = duplicate_detector
        self._editor = editor
        self._publisher = publisher
        self._repo = repository
        self._min_relevance = min_relevance_score
        self._max_offers = max_offers_per_run
        self._europe_boost = europe_boost
        self._spain_per_run = spain_offers_per_run

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

        # 3. Filter by minimum relevance (raw LLM score) and rank by priority
        # (relevance ± the Europe-friendliness boost).
        candidates = [
            it
            for it in classified
            if it.relevance_score and it.relevance_score.is_at_least(self._min_relevance)
        ]
        report.discarded_low_relevance = len(classified) - len(candidates)
        if not candidates:
            report.errors.append("Ninguna oferta superó el umbral de relevancia")
            return
        ranked = sorted(candidates, key=self._priority, reverse=True)

        # 4-7. Walk the ranked candidates: dedup, edit, publish, persist; stop
        # once the per-run cap is reached. One failing offer does not block the
        # rest of the batch. Spain-based offers get their reserved slots first;
        # unused slots (no unique Spain offer today) go back to the general pool.
        # At most one offer per company makes it into the same run.
        processed: set[str] = set()
        published_companies: set[str] = set()

        async def try_publish(candidate: JobOffer) -> bool:
            company = candidate.company.strip().lower()
            if company and company in published_companies:
                report.discarded_same_company += 1
                logger.info(
                    "workflow.same_company_skipped",
                    title=candidate.title,
                    company=candidate.company,
                )
                return False
            if await self._publish_offer(candidate, report):
                if company:
                    published_companies.add(company)
                return True
            return False

        spain_target = min(self._spain_per_run, self._max_offers)
        spain_published = 0
        for candidate in (c for c in ranked if is_spain_offer(c)):
            if spain_published >= spain_target or report.published >= self._max_offers:
                break
            processed.add(candidate.url_fingerprint)
            if await try_publish(candidate):
                spain_published += 1

        for candidate in ranked:
            if report.published >= self._max_offers:
                break
            if candidate.url_fingerprint in processed:
                continue
            processed.add(candidate.url_fingerprint)
            await try_publish(candidate)

        await self._repo.increment_counter(
            "discarded", report.discarded_duplicates + report.discarded_low_relevance
        )
        if report.published == 0 and not report.errors:
            report.errors.append("Todas las ofertas candidatas eran duplicadas")

    def _priority(self, offer: JobOffer) -> int:
        """Ordering score: relevance adjusted by Europe-friendliness."""
        score = offer.relevance_score.value if offer.relevance_score else 0
        friendly = europe_friendly(offer)
        if friendly is True:
            score += self._europe_boost
        elif friendly is False:
            score -= self._europe_boost
        return score

    async def _publish_offer(self, candidate: JobOffer, report: WorkflowReport) -> bool:
        """Dedup-check, edit, publish and persist one candidate.

        Returns True when the offer ended up published.
        """
        decision = await self._duplicate_detector.run(candidate)
        if decision.is_duplicate:
            report.discarded_duplicates += 1
            return False

        try:
            edited = await self._editor.run(candidate)
            post = PublishableJobOffer(offer=candidate, edited=edited)
            published = await self._publisher.run(post)
            offer_id = await self._repo.save_published(published, decision.embedding)
        except Exception as exc:
            logger.exception("workflow.offer_failed", title=candidate.title)
            report.errors.append(f"{candidate.title}: {exc}")
            return False

        await self._repo.increment_counter("published", 1)
        metrics.increment("offers_published")
        report.published += 1
        report.published_offers.append(published)
        logger.info(
            "workflow.published",
            offer_id=offer_id,
            title=edited.title,
            spain=is_spain_offer(candidate),
        )
        return True
