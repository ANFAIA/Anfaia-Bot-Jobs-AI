"""Pydantic v2 input/output schemas for the REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities import WorkflowReport
from app.interfaces.repositories import StatsSnapshot, StoredJobOffer


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str


class JobOfferResponse(BaseModel):
    id: int
    title: str
    url: str
    company: str
    source: str
    category: str
    modality: str
    location: str
    salary: str
    seniority: str
    relevance_score: int
    summary: str
    published_at: datetime | None
    discord_message_id: int | None
    created_at: datetime

    @classmethod
    def from_domain(cls, offer: StoredJobOffer) -> JobOfferResponse:
        return cls(
            id=offer.id,
            title=offer.title,
            url=offer.url,
            company=offer.company,
            source=offer.source,
            category=offer.category.value,
            modality=offer.modality,
            location=offer.location,
            salary=offer.salary,
            seniority=offer.seniority,
            relevance_score=offer.relevance_score,
            summary=offer.summary,
            published_at=offer.published_at,
            discord_message_id=offer.discord_message_id,
            created_at=offer.created_at,
        )


class WorkflowRunResponse(BaseModel):
    status: str
    collected: int
    classified: int
    published: int
    discarded_duplicates: int
    discarded_low_relevance: int
    errors: list[str]
    published_titles: list[str]
    discord_message_ids: list[int]

    @classmethod
    def from_report(cls, report: WorkflowReport) -> WorkflowRunResponse:
        return cls(
            status="success" if report.succeeded else "failed",
            collected=report.collected,
            classified=report.classified,
            published=report.published,
            discarded_duplicates=report.discarded_duplicates,
            discarded_low_relevance=report.discarded_low_relevance,
            errors=report.errors,
            published_titles=[post.edited.title for post in report.published_offers],
            discord_message_ids=[
                post.discord_message_id
                for post in report.published_offers
                if post.discord_message_id is not None
            ],
        )


class DiscordTestRequest(BaseModel):
    message: str = Field(
        default="Mensaje de prueba de Anfaia Jobs AI 💼",
        max_length=1500,
    )


class DiscordTestResponse(BaseModel):
    status: str = "sent"
    discord_message_id: int


class StatsResponse(BaseModel):
    analyzed: int
    published: int
    discarded: int
    by_category: dict[str, int]
    last_run_at: str | None
    last_run_status: str | None

    @classmethod
    def from_snapshot(cls, snapshot: StatsSnapshot) -> StatsResponse:
        return cls(
            analyzed=snapshot.analyzed,
            published=snapshot.published,
            discarded=snapshot.discarded,
            by_category=snapshot.by_category,
            last_run_at=snapshot.last_run_at,
            last_run_status=snapshot.last_run_status,
        )
