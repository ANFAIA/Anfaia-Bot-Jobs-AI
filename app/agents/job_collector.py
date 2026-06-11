"""Agent 1 — Job Collector.

Collects job offers from all configured sources in parallel, normalizes them to
`JobOffer`, removes exact URL duplicates within the same batch and applies the
optional keyword pre-filter (so only potentially relevant offers reach the LLM
classifier).
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.interfaces.agent import Agent
from app.interfaces.job_source import JobSource

logger = get_logger(__name__)


class JobCollectorAgent(Agent[None, list[JobOffer]]):
    """Aggregates and normalizes job offers from multiple sources."""

    name = "job_collector"

    def __init__(
        self,
        sources: list[JobSource],
        *,
        max_items_per_source: int,
        keywords: list[str] | None = None,
    ) -> None:
        self._sources = sources
        self._max_items_per_source = max_items_per_source
        self._keywords = [kw.lower() for kw in (keywords or [])]

    async def run(self, input_data: None = None) -> list[JobOffer]:
        results = await asyncio.gather(
            *(source.fetch(self._max_items_per_source) for source in self._sources),
            return_exceptions=True,
        )

        collected: list[JobOffer] = []
        for source, result in zip(self._sources, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("collector.source_error", source=source.name, error=str(result))
                continue
            collected.extend(result)

        deduped = self._dedupe(collected)
        filtered = [offer for offer in deduped if self._matches_keywords(offer)]
        logger.info(
            "collector.done",
            raw=len(collected),
            unique=len(deduped),
            matching=len(filtered),
            sources=len(self._sources),
        )
        return filtered

    def _matches_keywords(self, offer: JobOffer) -> bool:
        if not self._keywords:
            return True
        haystack = " ".join((offer.title, " ".join(offer.tags), offer.summary)).lower()
        return any(kw in haystack for kw in self._keywords)

    @staticmethod
    def _dedupe(offers: list[JobOffer]) -> list[JobOffer]:
        seen: set[str] = set()
        unique: list[JobOffer] = []
        for offer in offers:
            fp = offer.url_fingerprint
            if fp in seen:
                continue
            seen.add(fp)
            unique.append(offer)
        return unique
