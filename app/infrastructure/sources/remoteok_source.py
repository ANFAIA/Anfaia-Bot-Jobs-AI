"""Job source for the RemoteOK public API.

RemoteOK (https://remoteok.com) serves its whole board as JSON at
`GET https://remoteok.com/api`. The first element of the array is a legal
notice, not a job. No API key is required, but a User-Agent header is (the
shared httpx client already sets one).
"""

from __future__ import annotations

from datetime import datetime
from html import unescape

import httpx
from dateutil import parser as dateparser

from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.domain.value_objects import Modality
from app.infrastructure.sources.text import clean_html, truncate
from app.interfaces.job_source import JobSource

logger = get_logger(__name__)

_API_URL = "https://remoteok.com/api"


class RemoteOKSource(JobSource):
    """Source that reads remote jobs from the RemoteOK API."""

    def __init__(self, *, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "RemoteOK"

    @staticmethod
    def _parse_date(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return dateparser.parse(raw)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _format_salary(job: dict) -> str:
        minimum, maximum = job.get("salary_min"), job.get("salary_max")
        if minimum and maximum:
            return f"${int(minimum):,} - ${int(maximum):,}"
        if minimum:
            return f"desde ${int(minimum):,}"
        return ""

    async def fetch(self, limit: int) -> list[JobOffer]:
        try:
            response = await self._client.get(_API_URL)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("source.fetch_failed", source=self.name, error=str(exc))
            return []

        offers: list[JobOffer] = []
        # Skip non-job entries (the API prepends a legal-notice object).
        jobs = [item for item in payload if isinstance(item, dict) and item.get("position")]
        for job in jobs[:limit]:
            url = job.get("url")
            title = job.get("position")
            if not url or not title:
                continue
            description = clean_html(job.get("description") or "")
            offers.append(
                JobOffer(
                    # The API returns titles/companies with raw HTML entities.
                    title=unescape(title).strip(),
                    url=url.strip(),
                    company=unescape(job.get("company") or "").strip(),
                    source=self.name,
                    summary=truncate(description, 800),
                    location=(job.get("location") or "").strip(),
                    salary=self._format_salary(job),
                    modality=Modality.REMOTE,  # RemoteOK only lists remote jobs
                    tags=tuple(str(t) for t in job.get("tags") or ()),
                    published_at=self._parse_date(job.get("date")),
                    raw_content=truncate(description, 4000),
                )
            )
        logger.info("source.fetched", source=self.name, count=len(offers))
        return offers
