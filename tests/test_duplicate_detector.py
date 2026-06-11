"""Duplicate Detector agent over the in-memory repository."""

from __future__ import annotations

from app.agents.duplicate_detector import DuplicateDetectorAgent
from app.domain.entities import PublishableJobOffer
from app.domain.value_objects import Category, RelevanceScore
from app.infrastructure.embeddings.hash_embeddings import HashEmbeddingProvider
from app.infrastructure.persistence.in_memory import InMemoryJobRepository
from tests.conftest import editor_json, make_offer


def _publishable(offer):
    import json

    from app.domain.entities import EditedJobPost

    data = json.loads(editor_json())
    edited = EditedJobPost(
        title=data["title"],
        role_summary=data["role_summary"],
        requirements=data["requirements"],
        conditions=data["conditions"],
        why_interesting=data["why_interesting"],
        source_url=offer.url,
    )
    return PublishableJobOffer(offer=offer, edited=edited)


async def test_unique_offer_passes():
    repo = InMemoryJobRepository()
    agent = DuplicateDetectorAgent(repo, HashEmbeddingProvider(64), similarity_threshold=0.9)

    decision = await agent.run(make_offer())

    assert not decision.is_duplicate
    assert decision.reason == "unique"
    assert decision.embedding


async def test_detects_exact_url_duplicate():
    repo = InMemoryJobRepository()
    embeddings = HashEmbeddingProvider(64)
    offer = make_offer().with_classification(Category.AI_ML, RelevanceScore(80))
    await repo.save_published(_publishable(offer), await embeddings.embed(offer.embedding_text))
    agent = DuplicateDetectorAgent(repo, embeddings, similarity_threshold=0.9)

    decision = await agent.run(make_offer(url=offer.url + "?utm=x"))

    assert decision.is_duplicate
    assert decision.reason == "url_already_published"


async def test_detects_semantic_duplicate_cross_board():
    repo = InMemoryJobRepository()
    embeddings = HashEmbeddingProvider(64)
    offer = make_offer().with_classification(Category.AI_ML, RelevanceScore(80))
    await repo.save_published(_publishable(offer), await embeddings.embed(offer.embedding_text))
    agent = DuplicateDetectorAgent(repo, embeddings, similarity_threshold=0.9)

    # Same offer text, different board URL.
    decision = await agent.run(make_offer(url="https://otherboard.com/jobs/999"))

    assert decision.is_duplicate
    assert decision.reason == "semantically_similar"
