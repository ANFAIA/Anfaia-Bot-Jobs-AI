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
    async def publish_test_message(self, text: str) -> int:
        """Publish a test message; return the message id."""
