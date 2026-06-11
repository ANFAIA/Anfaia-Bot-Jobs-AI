"""Domain entities and value objects."""

from __future__ import annotations

import pytest

from app.domain.value_objects import Category, Modality, RelevanceScore
from tests.conftest import make_offer


class TestJobOffer:
    def test_url_fingerprint_ignores_query_and_trailing_slash(self):
        a = make_offer(url="https://example.com/jobs/1?utm_source=x")
        b = make_offer(url="https://example.com/jobs/1/")
        assert a.url_fingerprint == b.url_fingerprint

    def test_embedding_text_includes_company_and_title(self):
        offer = make_offer()
        assert "Acme AI" in offer.embedding_text
        assert "ML Engineer" in offer.embedding_text

    def test_with_classification_returns_enriched_copy(self):
        offer = make_offer()
        enriched = offer.with_classification(
            Category.AI_ML, RelevanceScore(90), seniority="senior"
        )
        assert offer.category is None
        assert enriched.category is Category.AI_ML
        assert enriched.relevance_score.value == 90
        assert enriched.seniority == "senior"


class TestCategory:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("AI/ML", Category.AI_ML),
            ("machine learning", Category.AI_ML),
            ("data science", Category.DATA),
            ("devops", Category.DEVOPS),
            ("full stack", Category.FULLSTACK),
            ("algo raro", Category.OTHER),
        ],
    )
    def test_from_str(self, raw: str, expected: Category):
        assert Category.from_str(raw) is expected


class TestModality:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("remoto", Modality.REMOTE),
            ("Hybrid", Modality.HYBRID),
            ("presencial", Modality.ONSITE),
            ("???", Modality.UNKNOWN),
        ],
    )
    def test_from_str(self, raw: str, expected: Modality):
        assert Modality.from_str(raw) is expected


class TestRelevanceScore:
    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            RelevanceScore(101)

    def test_clamped(self):
        assert RelevanceScore.clamped(150).value == 100
        assert RelevanceScore.clamped(-3).value == 0
