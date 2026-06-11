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


def build_workflow(
    offers,
    llm_responses,
    publisher,
    repo,
    *,
    max_offers=3,
    min_relevance=55,
    europe_boost=15,
    spain_offers=1,
):
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
        europe_boost=europe_boost,
        spain_offers_per_run=spain_offers,
    )


async def test_publishes_top_offers_up_to_cap(fake_publisher: FakePublisher):
    offers = [
        make_offer(title=f"Oferta {i}", url=f"https://example.com/jobs/{i}", company=f"Empresa {i}")
        for i in range(4)
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


async def test_europe_friendly_offers_outrank_restricted_ones(fake_publisher: FakePublisher):
    usa = make_offer(
        title="US Backend", url="https://example.com/jobs/usa", location="USA Only", tags=()
    )
    europe = make_offer(
        title="EU Backend", url="https://example.com/jobs/eu", location="Europe", tags=()
    )
    # The US offer scores higher on raw relevance, but the Europe boost (±15)
    # flips the ordering: 90-15=75 vs 85+15=100.
    responses = [classifier_json(score=90), classifier_json(score=85), editor_json("EU Backend")]
    repo = InMemoryJobRepository()
    workflow = build_workflow([usa, europe], responses, fake_publisher, repo, max_offers=1)

    report = await workflow.run()

    assert report.published == 1
    assert fake_publisher.published[0].offer.title == "EU Backend"


async def test_reserves_a_slot_for_spain_offers(fake_publisher: FakePublisher):
    internationals = [
        make_offer(
            title=f"Remote {i}",
            url=f"https://example.com/jobs/{i}",
            company=f"Empresa {i}",
            location="Worldwide",
        )
        for i in range(3)
    ]
    spain = make_offer(
        title="ML Engineer Madrid",
        url="https://example.com/jobs/madrid",
        company="Startup Madrid",
        location="Madrid, España",
        summary="Equipo de IA en Madrid construyendo modelos de lenguaje.",
    )
    # The Spain offer has the LOWEST relevance, yet the reserved slot gets it
    # published alongside the best international one.
    responses = [classifier_json(score=95 - i) for i in range(3)] + [classifier_json(score=60)]
    responses += [editor_json("Oferta España"), editor_json("Oferta internacional")]
    repo = InMemoryJobRepository()
    workflow = build_workflow(
        [*internationals, spain], responses, fake_publisher, repo, max_offers=2
    )

    report = await workflow.run()

    assert report.published == 2
    titles = {post.offer.title for post in fake_publisher.published}
    assert "ML Engineer Madrid" in titles
    assert "Remote 0" in titles


async def test_spain_quota_unused_when_no_spain_offers(fake_publisher: FakePublisher):
    offers = [
        make_offer(
            title=f"Remote {i}",
            url=f"https://example.com/jobs/{i}",
            company=f"Empresa {i}",
            location="Worldwide",
        )
        for i in range(2)
    ]
    responses = [classifier_json(score=90), classifier_json(score=80)]
    responses += [editor_json("A"), editor_json("B")]
    repo = InMemoryJobRepository()
    workflow = build_workflow(offers, responses, fake_publisher, repo, max_offers=2)

    report = await workflow.run()

    # Both general offers are published: the unused Spain slot goes back to
    # the general pool.
    assert report.published == 2


async def test_at_most_one_offer_per_company_per_run(fake_publisher: FakePublisher):
    acme = [
        make_offer(
            title=f"Acme role {i}",
            url=f"https://example.com/jobs/acme-{i}",
            company="Acme AI",
            location="Worldwide",
        )
        for i in range(3)
    ]
    beta = make_offer(
        title="Beta role",
        url="https://example.com/jobs/beta",
        company="Beta Labs",
        location="Worldwide",
    )
    # The three Acme offers outscore Beta, but only the best one gets through;
    # Beta fills the next slot.
    responses = [classifier_json(score=95 - i) for i in range(3)] + [classifier_json(score=70)]
    responses += [editor_json("Acme"), editor_json("Beta")]
    repo = InMemoryJobRepository()
    workflow = build_workflow([*acme, beta], responses, fake_publisher, repo, max_offers=3)

    report = await workflow.run()

    assert report.published == 2
    companies = [post.offer.company for post in fake_publisher.published]
    assert companies == ["Acme AI", "Beta Labs"]
    assert report.discarded_same_company == 2


async def test_offers_without_company_do_not_block_each_other(fake_publisher: FakePublisher):
    offers = [
        make_offer(
            title=f"Anon {i}",
            url=f"https://example.com/jobs/anon-{i}",
            company="",
            location="Worldwide",
        )
        for i in range(2)
    ]
    responses = [classifier_json(score=90), classifier_json(score=80)]
    responses += [editor_json("A"), editor_json("B")]
    repo = InMemoryJobRepository()
    workflow = build_workflow(offers, responses, fake_publisher, repo, max_offers=2)

    report = await workflow.run()

    assert report.published == 2
    assert report.discarded_same_company == 0


async def test_empty_collection_reports_error(fake_publisher: FakePublisher):
    repo = InMemoryJobRepository()
    workflow = build_workflow([], [], fake_publisher, repo)

    report = await workflow.run()

    assert not report.succeeded
    assert report.errors
