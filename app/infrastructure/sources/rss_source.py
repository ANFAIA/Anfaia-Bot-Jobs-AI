"""Generic job source based on RSS/Atom feeds.

Many job boards (We Work Remotely, regional portals, company career pages)
publish their offers as RSS. Downloads the feed with httpx (async) and parses
it with feedparser. Any network or parsing failure is caught and an empty list
is returned, so a single broken source never breaks the whole pipeline.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import feedparser
import httpx

from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.infrastructure.sources.text import clean_html, truncate
from app.interfaces.job_source import JobSource

logger = get_logger(__name__)


class RSSJobSource(JobSource):
    """Source that reads job offers from a single RSS/Atom feed.

    Feeds rarely separate company from role; many (e.g. We Work Remotely) use
    the "Company: Role" convention in the title, which we split heuristically.
    """

    def __init__(self, name: str, feed_url: str, *, client: httpx.AsyncClient) -> None:
        self._name = name
        self._feed_url = feed_url
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def _parse_date(entry: feedparser.FeedParserDict) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed:
            return None
        return datetime.fromtimestamp(time.mktime(parsed), tz=UTC)

    @staticmethod
    def _split_company(title: str) -> tuple[str, str]:
        """Split a feed title into (company, role).

        Handles the two common conventions: "Company: Role" (We Work Remotely)
        and "Role at Company" (Real Work From Anywhere and others). Titles that
        match neither are kept whole as the role, with an empty company.
        """
        company, sep, role = title.partition(":")
        if sep and company.strip() and role.strip():
            return company.strip(), role.strip()
        role, sep, company = title.rpartition(" at ")
        if sep and role.strip() and company.strip():
            return company.strip(), role.strip()
        return "", title.strip()

    async def fetch(self, limit: int) -> list[JobOffer]:
        try:
            response = await self._client.get(self._feed_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("source.fetch_failed", source=self._name, error=str(exc))
            return []

        feed = feedparser.parse(response.content)
        offers: list[JobOffer] = []
        for entry in feed.entries[:limit]:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            company, role = self._split_company(title.strip())
            summary = clean_html(entry.get("summary") or entry.get("description") or "")
            tags = tuple(t.get("term", "") for t in entry.get("tags", []) if t.get("term"))
            offers.append(
                JobOffer(
                    title=role,
                    url=link.strip(),
                    company=company,
                    source=self._name,
                    summary=truncate(summary, 800),
                    tags=tags,
                    published_at=self._parse_date(entry),
                    raw_content=truncate(summary, 4000),
                )
            )
        logger.info("source.fetched", source=self._name, count=len(offers))
        return offers
