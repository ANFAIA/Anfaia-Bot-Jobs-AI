"""Agent 5 — Discord Publisher.

Thin wrapper over the `Publisher` port that exposes publishing as one more
agent in the pipeline, preserving the symmetry of the multi-agent system.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.domain.entities import PublishableJobOffer
from app.interfaces.agent import Agent
from app.interfaces.publisher import Publisher

logger = get_logger(__name__)


class DiscordPublisherAgent(Agent[PublishableJobOffer, PublishableJobOffer]):
    """Publishes the final job post and returns it with the message id."""

    name = "discord_publisher"

    def __init__(self, publisher: Publisher) -> None:
        self._publisher = publisher

    async def run(self, input_data: PublishableJobOffer) -> PublishableJobOffer:
        message_id = await self._publisher.publish(input_data)
        logger.info("publisher.done", message_id=message_id, title=input_data.edited.title)
        return input_data.published_as(message_id)

    async def run_batch(
        self, posts: list[PublishableJobOffer], *, summary_date: str
    ) -> list[PublishableJobOffer | None]:
        """Publish the day's batch (summary + thread) and tag each post with its id.

        Returns a list aligned with ``posts``: each entry carries its Discord
        message id, or is ``None`` when that single offer could not be sent.
        """
        message_ids = await self._publisher.publish_batch(posts, summary_date=summary_date)
        results = [
            post.published_as(message_id) if message_id is not None else None
            for post, message_id in zip(posts, message_ids, strict=True)
        ]
        logger.info(
            "publisher.batch_done",
            published=sum(1 for post in results if post is not None),
            total=len(posts),
        )
        return results
