"""End-to-end daily workflow with test doubles (no network, no DB)."""

from __future__ import annotations

from app.agents.discord_publisher_agent import DiscordPublisherAgent
from app.agents.duplicate_detector import DuplicateDetectorAgent
from app.agents.job_classifier import JobClassifierAgent
from app.agents.job_collector import JobCollectorAgent
from app.agents.job_editor import JobEditorAgent
from app.infrastructure.embeddings.hash_embeddings import HashEmbeddingProvider
from app.infrastructure.persistence.in_memory import InMemoryJobRepository
from app.workflows.daily_jobs_workflow import DailyJobsWorkflow
from tests.conftest import (
    FakeLLM,
    FakePublisher,
    StaticSource,
    classifier_json,
    editor_json,
    make_offer,
)


def build_workflow(offers, llm_responses, publisher, repo, *, max_offers=3, min_relevance=55):
    embeddings = HashEmbeddingProvider(64)
    llm = FakeLLM(llm_responses)
    return DailyJobsWorkflow(
        collector=JobCollectorAgent([StaticSource("test", offers)], max_items_per_source=50),
        classifier=JobClassifierAgent(llm),
        duplicate_detector=DuplicateDetectorAgent(repo, embeddings, similarity_threshold=0.95),
        editor=JobEditorAgent(llm),
        publisher=DiscordPublisherAgent(publisher),
        repository=repo,
        min_relevance_score=min_relevance,
        max_offers_per_run=max_offers,
    )


async def test_publishes_top_offers_up_to_cap(fake_publisher: FakePublisher):
    offers = [
        make_offer(title=f"Oferta {i}", url=f"https://example.com/jobs/{i}") for i in range(4)
    ]
    # Classification responses are consumed concurrently; then one editor
    # response per published offer (cap = 2).
    responses = [classifier_json(score=90 - i) for i in range(4)]
    responses += [editor_json(f"Oferta editada {i}") for i in range(2)]
    repo = InMemoryJobRepository()
    workflow = build_workflow(offers, responses, fake_publisher, repo, max_offers=2)

    report = await workflow.run()

    assert report.succeeded
    assert report.published == 2
    assert len(fake_publisher.published) == 2
    assert len(await repo.list_offers(limit=10, offset=0)) == 2


async def test_discards_low_relevance(fake_publisher: FakePublisher):
    offers = [make_offer(url="https://example.com/jobs/low")]
    repo = InMemoryJobRepository()
    workflow = build_workflow(
        offers, [classifier_json(score=10)], fake_publisher, repo, min_relevance=55
    )

    report = await workflow.run()

    assert not report.succeeded
    assert report.discarded_low_relevance == 1
    assert report.published == 0


async def test_skips_already_published_duplicates(fake_publisher: FakePublisher):
    offer = make_offer(url="https://example.com/jobs/dup")
    repo = InMemoryJobRepository()
    # First run publishes the offer.
    first = build_workflow([offer], [classifier_json(), editor_json()], fake_publisher, repo)
    assert (await first.run()).published == 1

    # Second run sees the same offer again: duplicate, nothing published.
    second = build_workflow([offer], [classifier_json()], fake_publisher, repo)
    report = await second.run()

    assert report.published == 0
    assert report.discarded_duplicates == 1


async def test_empty_collection_reports_error(fake_publisher: FakePublisher):
    repo = InMemoryJobRepository()
    workflow = build_workflow([], [], fake_publisher, repo)

    report = await workflow.run()

    assert not report.succeeded
    assert report.errors
