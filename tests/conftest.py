"""Shared fixtures and test doubles."""

from __future__ import annotations

import json

import pytest

from app.domain.entities import JobOffer, PublishableJobOffer
from app.domain.value_objects import Modality
from app.interfaces.job_source import JobSource
from app.interfaces.llm import ChatMessage, LLMProvider
from app.interfaces.publisher import Publisher


class FakeLLM(LLMProvider):
    """LLM double that returns canned responses (or raises)."""

    def __init__(self, responses: list[str] | None = None, *, error: Exception | None = None):
        self._responses = list(responses or [])
        self._error = error
        self.calls: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError("FakeLLM sin respuestas restantes")
        return self._responses.pop(0)


class StaticSource(JobSource):
    """Source double that returns a fixed list of offers."""

    def __init__(self, name: str, offers: list[JobOffer]):
        self._name = name
        self._offers = offers

    @property
    def name(self) -> str:
        return self._name

    async def fetch(self, limit: int) -> list[JobOffer]:
        return self._offers[:limit]


class FakePublisher(Publisher):
    """Publisher double that records the published posts."""

    def __init__(self):
        self.published: list[PublishableJobOffer] = []
        self._next_id = 1000

    async def publish(self, post: PublishableJobOffer) -> int:
        self.published.append(post)
        self._next_id += 1
        return self._next_id

    async def publish_test_message(self, text: str) -> int:
        return 1


def make_offer(
    title: str = "ML Engineer",
    url: str = "https://example.com/jobs/ml-engineer",
    company: str = "Acme AI",
    summary: str = "Construirás pipelines de machine learning con Python.",
    **kwargs,
) -> JobOffer:
    """Build a JobOffer with sensible defaults for tests."""
    defaults = {
        "source": "TestBoard",
        "location": "Remote (EU)",
        "modality": Modality.REMOTE,
        "tags": ("python", "ml"),
    }
    defaults.update(kwargs)
    return JobOffer(title=title, url=url, company=company, summary=summary, **defaults)


def classifier_json(category: str = "AI/ML", score: int = 88, seniority: str = "senior") -> str:
    return json.dumps(
        {
            "category": category,
            "relevance_score": score,
            "seniority": seniority,
            "reason": "test",
        }
    )


def editor_json(title: str = "ML Engineer — Acme AI") -> str:
    return json.dumps(
        {
            "title": title,
            "role_summary": "Entrenarás y desplegarás modelos.",
            "requirements": "Python, ML, 3 años de experiencia.",
            "conditions": "Remoto UE, salario no consta.",
            "why_interesting": "Rol de IA con stack moderno.",
        }
    )


@pytest.fixture
def fake_publisher() -> FakePublisher:
    return FakePublisher()
