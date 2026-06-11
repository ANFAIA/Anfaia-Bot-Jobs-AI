"""Geographic heuristics: Europe-friendliness and Spain detection."""

from __future__ import annotations

from app.domain.geo import europe_friendly, is_spain_offer
from tests.conftest import make_offer


class TestEuropeFriendly:
    def test_explicit_europe_location(self):
        assert europe_friendly(make_offer(location="Europe")) is True

    def test_worldwide_counts_as_europe_friendly(self):
        assert europe_friendly(make_offer(location="Worldwide")) is True

    def test_usa_only_is_not_friendly(self):
        assert europe_friendly(make_offer(location="USA Only", tags=())) is False

    def test_region_in_summary_is_used_as_fallback(self):
        offer = make_offer(
            location="",
            tags=(),
            summary="Fully remote role, open to candidates anywhere in EMEA.",
        )
        assert europe_friendly(offer) is True

    def test_unknown_region_is_neutral(self):
        offer = make_offer(location="", tags=(), summary="Gran equipo y buen producto.")
        assert europe_friendly(offer) is None

    def test_spain_offers_are_always_friendly(self):
        assert europe_friendly(make_offer(location="Madrid", tags=())) is True


class TestIsSpainOffer:
    def test_detects_by_location(self):
        assert is_spain_offer(make_offer(location="Barcelona, España"))

    def test_detects_by_source(self):
        offer = make_offer(location="", tags=(), source="SEPE · Informática/Telecomunicaciones")
        assert is_spain_offer(offer)

    def test_international_offer_is_not_spain(self):
        assert not is_spain_offer(make_offer(location="Berlin, Germany", tags=()))
