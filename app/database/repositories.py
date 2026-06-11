"""SQLAlchemy implementation of the job repository.

Uses pgvector for similarity search (cosine distance). Similarity is derived as
`1 - cosine_distance`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.models import JobEmbedding, JobOfferRow, WorkflowCounter
from app.database.session import Database
from app.domain.entities import PublishableJobOffer
from app.domain.value_objects import Category
from app.interfaces.repositories import (
    JobRepository,
    SimilarOffer,
    StatsSnapshot,
    StoredJobOffer,
)

COUNTER_ANALYZED = "analyzed"
COUNTER_PUBLISHED = "published"
COUNTER_DISCARDED = "discarded"


class SqlAlchemyJobRepository(JobRepository):
    """Job repository backed by PostgreSQL + pgvector."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def url_exists(self, url_fingerprint: str) -> bool:
        async with self._db.session() as session:
            stmt = select(JobOfferRow.id).where(JobOfferRow.url_fingerprint == url_fingerprint)
            return (await session.execute(stmt)).first() is not None

    async def find_similar(
        self, embedding: list[float], threshold: float, limit: int = 5
    ) -> list[SimilarOffer]:
        max_distance = 1.0 - threshold
        distance = JobEmbedding.embedding.cosine_distance(embedding)
        async with self._db.session() as session:
            stmt = (
                select(
                    JobEmbedding.offer_id,
                    JobOfferRow.url,
                    distance.label("distance"),
                )
                .join(JobOfferRow, JobOfferRow.id == JobEmbedding.offer_id)
                .where(distance <= max_distance)
                .order_by(distance)
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()
        return [
            SimilarOffer(offer_id=r.offer_id, url=r.url, similarity=1.0 - r.distance)
            for r in rows
        ]

    async def save_published(
        self, post: PublishableJobOffer, embedding: list[float] | None
    ) -> int:
        offer = post.offer
        async with self._db.session() as session:
            orm_offer = JobOfferRow(
                title=offer.title,
                url=offer.url,
                url_fingerprint=offer.url_fingerprint,
                company=offer.company,
                source=offer.source,
                category=post.category.value,
                modality=offer.modality.value,
                location=offer.location,
                salary=offer.salary,
                seniority=offer.seniority or "unknown",
                published_at=offer.published_at,
                relevance_score=post.relevance_score.value,
                summary=offer.summary,
                discord_message_id=post.discord_message_id,
            )
            session.add(orm_offer)
            await session.flush()
            if embedding is not None:
                session.add(JobEmbedding(offer_id=orm_offer.id, embedding=embedding))
            await session.flush()
            return orm_offer.id

    async def increment_counter(self, name: str, amount: int = 1) -> None:
        async with self._db.session() as session:
            stmt = (
                pg_insert(WorkflowCounter)
                .values(name=name, value=amount)
                .on_conflict_do_update(
                    index_elements=[WorkflowCounter.name],
                    set_={"value": WorkflowCounter.value + amount},
                )
            )
            await session.execute(stmt)

    async def list_offers(
        self, *, limit: int, offset: int, category: Category | None = None
    ) -> list[StoredJobOffer]:
        async with self._db.session() as session:
            stmt = select(JobOfferRow).order_by(JobOfferRow.created_at.desc())
            if category is not None:
                stmt = stmt.where(JobOfferRow.category == category.value)
            stmt = stmt.limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
        return [self._to_stored(row) for row in rows]

    async def get_offer(self, offer_id: int) -> StoredJobOffer | None:
        async with self._db.session() as session:
            row = await session.get(JobOfferRow, offer_id)
            return self._to_stored(row) if row else None

    async def stats(self) -> StatsSnapshot:
        async with self._db.session() as session:
            counters = dict(
                (await session.execute(select(WorkflowCounter.name, WorkflowCounter.value))).all()
            )
            by_category = dict(
                (
                    await session.execute(
                        select(JobOfferRow.category, func.count()).group_by(JobOfferRow.category)
                    )
                ).all()
            )
            published = (
                await session.execute(select(func.count()).select_from(JobOfferRow))
            ).scalar_one()

        return StatsSnapshot(
            analyzed=counters.get(COUNTER_ANALYZED, 0),
            published=max(counters.get(COUNTER_PUBLISHED, 0), published),
            discarded=counters.get(COUNTER_DISCARDED, 0),
            by_category=by_category,
            last_run_at=None,
            last_run_status=None,
        )

    @staticmethod
    def _to_stored(row: JobOfferRow) -> StoredJobOffer:
        return StoredJobOffer(
            id=row.id,
            title=row.title,
            url=row.url,
            company=row.company,
            source=row.source,
            category=Category.from_str(row.category),
            modality=row.modality,
            location=row.location,
            salary=row.salary,
            seniority=row.seniority,
            relevance_score=row.relevance_score,
            summary=row.summary,
            published_at=row.published_at,
            discord_message_id=row.discord_message_id,
            created_at=row.created_at,
        )
