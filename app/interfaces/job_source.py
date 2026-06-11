"""Job source port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities import JobOffer


class JobSource(ABC):
    """A source from which normalized job offers can be collected."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the source (e.g. 'Remotive')."""

    @abstractmethod
    async def fetch(self, limit: int) -> list[JobOffer]:
        """Collect up to `limit` offers already normalized to `JobOffer`.

        Implementations must NOT raise exceptions on network failures: they
        should catch them, log them, and return whatever they managed to obtain
        (ideally an empty list) so as not to break the rest of the pipeline.
        """
