"""Job source for the Arbeitnow public API.

Arbeitnow (https://www.arbeitnow.com) exposes a free JSON job board (mostly
EU-based jobs) at `GET https://www.arbeitnow.com/api/job-board-api`. No API key
is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.domain.value_objects import Modality
from app.infrastructure.sources.text import clean_html, truncate
from app.interfaces.job_source import JobSource

logger = get_logger(__name__)

_API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource(JobSource):
    """Source that reads jobs from the Arbeitnow job-board API."""

    def __init__(self, *, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "Arbeitnow"

    @staticmethod
    def _parse_date(raw: object) -> datetime | None:
        # `created_at` is a unix timestamp.
        if not isinstance(raw, (int, float)) or raw <= 0:
            return None
        return datetime.fromtimestamp(raw, tz=UTC)

    async def fetch(self, limit: int) -> list[JobOffer]:
        try:
            response = await self._client.get(_API_URL)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("source.fetch_failed", source=self.name, error=str(exc))
            return []

        offers: list[JobOffer] = []
        for job in payload.get("data", [])[:limit]:
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
                    location=(job.get("location") or "").strip(),
                    modality=Modality.REMOTE if job.get("remote") else Modality.UNKNOWN,
                    tags=tuple(
                        str(t) for t in (*(job.get("tags") or ()), *(job.get("job_types") or ()))
                    ),
                    published_at=self._parse_date(job.get("created_at")),
                    raw_content=truncate(description, 4000),
                )
            )
        logger.info("source.fetched", source=self.name, count=len(offers))
        return offers
