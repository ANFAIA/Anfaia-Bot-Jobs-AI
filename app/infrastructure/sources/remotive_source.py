"""Job source for the Remotive public API.

Remotive (https://remotive.com) exposes a free JSON API of remote jobs:
`GET https://remotive.com/api/remote-jobs?category=<slug>&limit=<n>`. No API
key is required. Any network or parsing failure is caught and an empty list is
returned, so a single broken source never breaks the whole pipeline.
"""

from __future__ import annotations

from datetime import datetime

import httpx
from dateutil import parser as dateparser

from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.domain.value_objects import Modality
from app.infrastructure.sources.text import clean_html, truncate
from app.interfaces.job_source import JobSource

logger = get_logger(__name__)

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    """Source that reads remote jobs from the Remotive API."""

    def __init__(self, *, client: httpx.AsyncClient, category: str = "software-dev") -> None:
        self._client = client
        self._category = category

    @property
    def name(self) -> str:
        return "Remotive"

    @staticmethod
    def _parse_date(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return dateparser.parse(raw)
        except (ValueError, OverflowError):
            return None

    async def fetch(self, limit: int) -> list[JobOffer]:
        try:
            response = await self._client.get(
                _API_URL, params={"category": self._category, "limit": limit}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("source.fetch_failed", source=self.name, error=str(exc))
            return []

        offers: list[JobOffer] = []
        for job in payload.get("jobs", [])[:limit]:
            url = job.get("url")
            title = job.get("title")
            if not url or not title:
                continue
            description = clean_html(job.get("description") or "")
            offers.append(
                JobOffer(
                    title=title.strip(),
                    url=url.strip(),
                    company=(job.get("company_name") or "").strip(),
                    source=self.name,
                    summary=truncate(description, 800),
                    location=(job.get("candidate_required_location") or "").strip(),
                    salary=(job.get("salary") or "").strip(),
                    modality=Modality.REMOTE,  # Remotive only lists remote jobs
                    tags=tuple(str(t) for t in job.get("tags") or ()),
                    published_at=self._parse_date(job.get("publication_date")),
                    raw_content=truncate(description, 4000),
                )
            )
        logger.info("source.fetched", source=self.name, count=len(offers))
        return offers
