"""Sequential implementation of the daily jobs workflow.

Pipeline:

    Collect Offers → Classify → Rank (Europe-friendly first) → Remove Duplicates
    → Edit Job Post → (collect the top N unique offers)
    → Publish daily batch to Discord (summary message + a thread of offers)
    → Save History

It is a custom implementation (without an orchestration framework) that honors
the `JobsWorkflow` contract. Each step delegates to a specialized agent. Unlike
a news digest, a jobs channel benefits from several posts per run, so the
pipeline walks the ranked candidates, selects the top N unique offers and then
publishes them together: one summary message announcing the day's offers, with
every offer posted inside a thread hanging off that message.

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
from app.domain.similarity import cosine_similarity
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
        duplicate_similarity_threshold: float = 0.95,
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
        self._similarity_threshold = duplicate_similarity_threshold

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

        # 4-6. Walk the ranked candidates and SELECT the day's batch: dedup and
        # edit each one, collecting up to `max_offers` unique offers. Nothing is
        # published or persisted yet — that happens once, in a single batch, so
        # the whole run shows up as one summary message plus a thread of offers.
        # Spain-based offers get their reserved slots first; unused slots (no
        # unique Spain offer today) go back to the general pool. At most one
        # offer per company makes it into the same run.
        processed: set[str] = set()
        selected_companies: set[str] = set()
        selected: list[tuple[PublishableJobOffer, list[float]]] = []

        async def try_select(candidate: JobOffer) -> bool:
            company = candidate.company.strip().lower()
            if company and company in selected_companies:
                report.discarded_same_company += 1
                logger.info(
                    "workflow.same_company_skipped",
                    title=candidate.title,
                    company=candidate.company,
                )
                return False
            prepared = await self._prepare_offer(candidate, report, selected)
            if prepared is None:
                return False
            selected.append(prepared)
            if company:
                selected_companies.add(company)
            return True

        spain_target = min(self._spain_per_run, self._max_offers)
        spain_selected = 0
        for candidate in (c for c in ranked if is_spain_offer(c)):
            if spain_selected >= spain_target or len(selected) >= self._max_offers:
                break
            processed.add(candidate.url_fingerprint)
            if await try_select(candidate):
                spain_selected += 1

        for candidate in ranked:
            if len(selected) >= self._max_offers:
                break
            if candidate.url_fingerprint in processed:
                continue
            processed.add(candidate.url_fingerprint)
            await try_select(candidate)

        # 7-8. Publish the selected batch to Discord and persist whatever made
        # it through.
        await self._publish_and_persist(selected, report)

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

    async def _prepare_offer(
        self,
        candidate: JobOffer,
        report: WorkflowReport,
        selected: list[tuple[PublishableJobOffer, list[float]]],
    ) -> tuple[PublishableJobOffer, list[float]] | None:
        """Dedup-check and edit one candidate, returning it ready to publish.

        Returns the `(post, embedding)` pair when the offer should join the
        batch, or None if it is a duplicate or editing fails. Nothing is
        published or persisted here.
        """
        decision = await self._duplicate_detector.run(candidate)
        if decision.is_duplicate:
            report.discarded_duplicates += 1
            return None

        # The repository only knows past runs; catch the same offer cross-posted
        # on several boards WITHIN this run, before any of them is persisted.
        if any(
            cosine_similarity(decision.embedding, emb) >= self._similarity_threshold
            for _, emb in selected
        ):
            report.discarded_duplicates += 1
            logger.info("workflow.intra_run_duplicate", title=candidate.title)
            return None

        try:
            edited = await self._editor.run(candidate)
        except Exception as exc:
            logger.exception("workflow.offer_failed", title=candidate.title)
            report.errors.append(f"{candidate.title}: {exc}")
            return None

        post = PublishableJobOffer(offer=candidate, edited=edited)
        return post, decision.embedding

    async def _publish_and_persist(
        self,
        selected: list[tuple[PublishableJobOffer, list[float]]],
        report: WorkflowReport,
    ) -> None:
        """Publish the selected offers as one summary + thread, then save history.

        Persistence happens only for offers that actually reached Discord, so a
        publishing outage leaves them unsaved and they are retried on a later
        run instead of being silently buried as "already published".
        """
        if not selected:
            return

        posts = [post for post, _ in selected]
        summary_date = datetime.now(UTC).strftime("%d/%m/%Y")
        try:
            published = await self._publisher.run_batch(posts, summary_date=summary_date)
        except Exception as exc:
            logger.exception("workflow.batch_publish_failed")
            report.errors.append(str(exc))
            return

        for (_, embedding), result in zip(selected, published, strict=True):
            if result is None:
                continue
            try:
                offer_id = await self._repo.save_published(result, embedding)
            except Exception as exc:
                logger.exception("workflow.persist_failed", title=result.edited.title)
                report.errors.append(f"{result.edited.title}: {exc}")
                continue
            await self._repo.increment_counter("published", 1)
            metrics.increment("offers_published")
            report.published += 1
            report.published_offers.append(result)
            logger.info(
                "workflow.published",
                offer_id=offer_id,
                title=result.edited.title,
                spain=is_spain_offer(result.offer),
            )
