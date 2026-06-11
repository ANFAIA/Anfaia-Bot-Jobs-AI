"""Registry of the system's default job sources.

Centralizes the initial catalog of sources. The catalog can be overridden from
configuration (REMOTIVE_ENABLED, REMOTEOK_ENABLED, ARBEITNOW_ENABLED,
JOB_RSS_FEEDS) without touching agents or the workflow; the lists below are
only the defaults.
"""

from __future__ import annotations

import httpx

from app.infrastructure.sources.arbeitnow_source import ArbeitnowSource
from app.infrastructure.sources.remoteok_source import RemoteOKSource
from app.infrastructure.sources.remotive_source import RemotiveSource
from app.infrastructure.sources.rss_source import RSSJobSource
from app.interfaces.job_source import JobSource

# (human-readable name, RSS/Atom feed URL)
DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    # España / público: Portal Único de Empleo (SEPE), categoría Informática y
    # Telecomunicaciones. El feed puede no ser alcanzable desde algunas redes;
    # en ese caso la fuente degrada a lista vacía sin romper el pipeline.
    (
        "SEPE · Informática/Telecomunicaciones",
        "https://bnde.sistemanacionalempleo.es/es/portaltrabaja/resources/rss/"
        "Informatica_Telecomunicaciones.xml",
    ),
    # Remoto / internacional.
    (
        "We Work Remotely · Programming",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    ),
    (
        "We Work Remotely · DevOps",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ),
    ("Himalayas", "https://himalayas.app/jobs/rss"),
    ("Real Work From Anywhere", "https://www.realworkfromanywhere.com/rss.xml"),
]


def build_default_sources(
    client: httpx.AsyncClient,
    *,
    remotive_enabled: bool = True,
    remotive_category: str = "software-dev",
    remoteok_enabled: bool = True,
    arbeitnow_enabled: bool = True,
    rss_feeds: list[tuple[str, str]] | None = None,
) -> list[JobSource]:
    """Build the list of sources, honoring configuration overrides."""
    sources: list[JobSource] = []
    if remotive_enabled:
        sources.append(RemotiveSource(client=client, category=remotive_category))
    if remoteok_enabled:
        sources.append(RemoteOKSource(client=client))
    if arbeitnow_enabled:
        sources.append(ArbeitnowSource(client=client))
    feeds = DEFAULT_RSS_FEEDS if rss_feeds is None else rss_feeds
    sources.extend(RSSJobSource(name, url, client=client) for name, url in feeds)
    return sources
