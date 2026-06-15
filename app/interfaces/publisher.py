"""Publishing port (the content's outbound channel)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities import PublishableJobOffer


class PublisherError(RuntimeError):
    """Unrecoverable error while publishing to the outbound channel."""


class Publisher(ABC):
    """Publishes a job post to an external channel (Discord, etc.)."""

    @abstractmethod
    async def publish(self, post: PublishableJobOffer) -> int:
        """Publish the job post and return the identifier of the created message.

        Raises:
            PublisherError: if publishing fails permanently.
        """

    @abstractmethod
    async def publish_batch(
        self, posts: list[PublishableJobOffer], *, summary_date: str
    ) -> list[int | None]:
        """Publish a daily batch as one summary message plus a thread of offers.

        Posts a header announcing the day's offers, opens a thread on it and
        sends one message per offer inside that thread. Returns a list aligned
        with ``posts`` holding each offer's message id, or ``None`` where that
        single offer could not be sent.

        Raises:
            PublisherError: if the batch cannot be published at all (e.g. the
                connection or the summary/thread creation fails).
        """

    @abstractmethod
    async def publish_test_message(self, text: str) -> int:
        """Publish a test message; return the message id."""
