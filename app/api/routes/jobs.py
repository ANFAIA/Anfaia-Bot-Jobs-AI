"""Endpoints for querying the published offers history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import ContainerDep
from app.api.schemas import JobOfferResponse
from app.domain.value_objects import Category

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOfferResponse])
async def list_jobs(
    container: ContainerDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: Category | None = Query(default=None),
) -> list[JobOfferResponse]:
    """List published job offers, optionally filtered by category."""
    offers = await container.list_jobs_uc.execute(limit=limit, offset=offset, category=category)
    return [JobOfferResponse.from_domain(o) for o in offers]


@router.get("/{offer_id}", response_model=JobOfferResponse)
async def get_job(offer_id: int, container: ContainerDep) -> JobOfferResponse:
    """Retrieve a specific job offer by id."""
    offer = await container.get_job_uc.execute(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    return JobOfferResponse.from_domain(offer)
