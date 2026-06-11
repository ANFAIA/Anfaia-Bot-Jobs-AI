"""Job Classifier agent: LLM path and heuristic fallback."""

from __future__ import annotations

from app.agents.job_classifier import JobClassifierAgent
from app.domain.value_objects import Category
from tests.conftest import FakeLLM, classifier_json, make_offer


async def test_classifies_with_llm():
    agent = JobClassifierAgent(FakeLLM([classifier_json("AI/ML", 92, "senior")]))

    classified = await agent.run(make_offer())

    assert classified.category is Category.AI_ML
    assert classified.relevance_score.value == 92
    assert classified.seniority == "senior"


async def test_invalid_seniority_normalized_to_unknown():
    agent = JobClassifierAgent(FakeLLM([classifier_json(seniority="principal architect")]))

    classified = await agent.run(make_offer())

    assert classified.seniority == "unknown"


async def test_falls_back_to_heuristic_on_llm_error():
    agent = JobClassifierAgent(FakeLLM(error=RuntimeError("api caída")))

    classified = await agent.run(
        make_offer(
            title="Machine Learning Engineer",
            summary="Buscamos perfil de machine learning y deep learning.",
        )
    )

    assert classified.category is Category.AI_ML
    assert classified.relevance_score is not None


async def test_heuristic_penalizes_spam():
    agent = JobClassifierAgent(FakeLLM(error=RuntimeError("api caída")))

    classified = await agent.run(
        make_offer(
            title="Rockstar ninja developer",
            summary="Gana dinero desde casa sin experiencia.",
            tags=(),
            salary="",
        )
    )

    assert classified.relevance_score.value < 50
