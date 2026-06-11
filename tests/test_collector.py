"""Job Collector agent: aggregation, dedup and keyword filtering."""

from __future__ import annotations

from app.agents.job_collector import JobCollectorAgent
from tests.conftest import StaticSource, make_offer


async def test_collects_from_all_sources_and_dedupes():
    offer = make_offer(url="https://example.com/jobs/1")
    duplicate = make_offer(url="https://example.com/jobs/1?ref=abc")
    other = make_offer(title="Data Engineer", url="https://example.com/jobs/2")
    agent = JobCollectorAgent(
        [StaticSource("a", [offer]), StaticSource("b", [duplicate, other])],
        max_items_per_source=10,
    )

    collected = await agent.run(None)

    assert len(collected) == 2
    assert {o.url for o in collected} == {offer.url, other.url}


async def test_keyword_filter_drops_unrelated_offers():
    ml = make_offer(title="ML Engineer", url="https://example.com/jobs/ml")
    chef = make_offer(
        title="Chef de cocina",
        url="https://example.com/jobs/chef",
        summary="Restaurante busca chef.",
        tags=(),
    )
    agent = JobCollectorAgent(
        [StaticSource("a", [ml, chef])],
        max_items_per_source=10,
        keywords=["ml", "python"],
    )

    collected = await agent.run(None)

    assert [o.title for o in collected] == ["ML Engineer"]


async def test_broken_source_does_not_break_the_batch():
    class BrokenSource(StaticSource):
        async def fetch(self, limit: int):
            raise RuntimeError("boom")

    ok = make_offer(url="https://example.com/jobs/ok")
    agent = JobCollectorAgent(
        [BrokenSource("broken", []), StaticSource("ok", [ok])],
        max_items_per_source=10,
    )

    collected = await agent.run(None)

    assert [o.url for o in collected] == [ok.url]
