"""Domain entities.

`JobOffer` is the central aggregate that flows through the entire agent
pipeline. Each agent progressively enriches it (classification, editing) until
it becomes a `PublishableJobOffer` ready for Discord.

The domain does not depend on SQLAlchemy, FastAPI or any concrete provider:
it only models business concepts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime

from app.domain.value_objects import Category, Modality, RelevanceScore


@dataclass(frozen=True, slots=True)
class JobOffer:
    """Normalized job offer coming from any source.

    It is immutable: agents produce enriched copies via `with_*`.
    """

    title: str
    url: str
    company: str
    source: str
    summary: str
    location: str = ""
    salary: str = ""
    modality: Modality = Modality.UNKNOWN
    tags: tuple[str, ...] = ()
    published_at: datetime | None = None
    raw_content: str = ""
    category: Category | None = None
    seniority: str = ""
    relevance_score: RelevanceScore | None = None

    @property
    def url_fingerprint(self) -> str:
        """Stable URL fingerprint for exact duplicate detection."""
        normalized = self.url.strip().lower().split("?")[0].rstrip("/")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @property
    def embedding_text(self) -> str:
        """Canonical text used to compute the semantic embedding.

        Company + title catch the same offer cross-posted on several boards
        even when each board rewrites the description.
        """
        return f"{self.company}\n{self.title}\n\n{self.summary}".strip()

    def with_classification(
        self, category: Category, score: RelevanceScore, *, seniority: str = ""
    ) -> JobOffer:
        return replace(self, category=category, relevance_score=score, seniority=seniority)


@dataclass(frozen=True, slots=True)
class EditedJobPost:
    """Edited content of a job offer, structured by sections."""

    title: str
    role_summary: str
    requirements: str
    conditions: str
    why_interesting: str
    source_url: str


@dataclass(frozen=True, slots=True)
class PublishableJobOffer:
    """Final job post ready to publish, aggregating all the agents' work."""

    offer: JobOffer
    edited: EditedJobPost
    discord_message_id: int | None = None

    @property
    def category(self) -> Category:
        assert self.offer.category is not None
        return self.offer.category

    @property
    def relevance_score(self) -> RelevanceScore:
        assert self.offer.relevance_score is not None
        return self.offer.relevance_score

    def published_as(self, message_id: int) -> PublishableJobOffer:
        return replace(self, discord_message_id=message_id)


@dataclass
class WorkflowReport:
    """Summary of the outcome of a daily workflow run."""

    collected: int = 0
    classified: int = 0
    discarded_duplicates: int = 0
    discarded_low_relevance: int = 0
    discarded_same_company: int = 0
    published: int = 0
    published_offers: list[PublishableJobOffer] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def succeeded(self) -> bool:
        return self.published > 0 and not self.errors
