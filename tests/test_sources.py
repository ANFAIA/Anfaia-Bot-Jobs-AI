"""Job source adapters against mocked HTTP responses (respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.domain.value_objects import Modality
from app.infrastructure.sources.arbeitnow_source import ArbeitnowSource
from app.infrastructure.sources.remotive_source import RemotiveSource
from app.infrastructure.sources.rss_source import RSSJobSource


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


class TestRSSTitleSplit:
    @pytest.mark.parametrize(
        ("title", "company", "role"),
        [
            ("Acme Corp: Senior Backend Engineer", "Acme Corp", "Senior Backend Engineer"),
            ("Account Executive at Instrumentl", "Instrumentl", "Account Executive"),
            ("Senior Thermal Engineer - Data Center", "", "Senior Thermal Engineer - Data Center"),
        ],
    )
    def test_split_company(self, title: str, company: str, role: str):
        assert RSSJobSource._split_company(title) == (company, role)


@respx.mock
async def test_remotive_normalizes_jobs(client: httpx.AsyncClient):
    respx.get("https://remotive.com/api/remote-jobs").respond(
        json={
            "jobs": [
                {
                    "url": "https://remotive.com/jobs/123",
                    "title": "ML Engineer",
                    "company_name": "Acme",
                    "description": "<p>Entrena modelos</p>",
                    "candidate_required_location": "Europe",
                    "salary": "60k-80k EUR",
                    "tags": ["python", "ml"],
                    "publication_date": "2026-06-01T00:00:00",
                }
            ]
        }
    )

    offers = await RemotiveSource(client=client).fetch(10)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.company == "Acme"
    assert offer.modality is Modality.REMOTE
    assert offer.salary == "60k-80k EUR"
    assert "Entrena modelos" in offer.summary
    assert "<p>" not in offer.summary


@respx.mock
async def test_remotive_network_error_returns_empty(client: httpx.AsyncClient):
    respx.get("https://remotive.com/api/remote-jobs").mock(
        side_effect=httpx.ConnectError("boom")
    )

    assert await RemotiveSource(client=client).fetch(10) == []


@respx.mock
async def test_arbeitnow_normalizes_jobs(client: httpx.AsyncClient):
    respx.get("https://www.arbeitnow.com/api/job-board-api").respond(
        json={
            "data": [
                {
                    "url": "https://arbeitnow.com/jobs/abc",
                    "title": "Data Engineer",
                    "company_name": "Beta GmbH",
                    "description": "ETL y pipelines",
                    "location": "Berlin",
                    "remote": True,
                    "tags": ["data"],
                    "job_types": ["full-time"],
                    "created_at": 1750000000,
                }
            ]
        }
    )

    offers = await ArbeitnowSource(client=client).fetch(10)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.company == "Beta GmbH"
    assert offer.modality is Modality.REMOTE
    assert "full-time" in offer.tags
    assert offer.published_at is not None
