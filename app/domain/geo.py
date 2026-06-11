"""Geographic heuristics over job offers.

The community is Spanish-speaking and mostly Europe-based, so the workflow
boosts offers that can be applied to from Europe and reserves a slot for offers
based in Spain. Detection is heuristic over the location/tags/source strings
the boards provide; the markers are deliberately conservative phrases to avoid
false positives, and an unknown region is left neutral (None).
"""

from __future__ import annotations

from app.domain.entities import JobOffer

# Phrases that signal the offer is open to applicants in Europe (or anywhere).
_EUROPE_MARKERS: tuple[str, ...] = (
    "europe",
    "european",
    "emea",
    "worldwide",
    "anywhere",
    "global",
    "remote (eu",
    "eu only",
    "españa",
    "spain",
    "portugal",
    "germany",
    "france",
    "netherlands",
    "italy",
    "ireland",
    "united kingdom",
    "utc+1",
    "utc+2",
)

# Phrases that signal the offer is restricted to regions incompatible with
# applying from Europe.
_NON_EUROPE_MARKERS: tuple[str, ...] = (
    "us only",
    "usa only",
    "us-only",
    "united states only",
    "us based",
    "us-based",
    "us residents",
    "north america",
    "americas only",
    "canada only",
    "latam only",
    "asia only",
    "australia only",
    "us timezone",
    "us time zone",
    "pacific time",
    "eastern time",
)

# Spain: country, autonomous-community capitals and common tech hubs.
_SPAIN_MARKERS: tuple[str, ...] = (
    "españa",
    "spain",
    "madrid",
    "barcelona",
    "valencia",
    "sevilla",
    "bilbao",
    "málaga",
    "malaga",
    "zaragoza",
    "alicante",
    "murcia",
    "granada",
    "vigo",
    "coruña",
    "gijón",
    "valladolid",
    "canarias",
    "baleares",
)

# Sources that only list Spanish offers (matched against the source name).
_SPAIN_SOURCES: tuple[str, ...] = ("sepe", "tecnoempleo", "empleorss", "infojobs")


def europe_friendly(offer: JobOffer) -> bool | None:
    """Whether the offer can be applied to from Europe.

    Returns True/False on a clear signal and None when the region cannot be
    determined. The structured fields (location, tags) are checked before the
    free-text summary, which is noisier.
    """
    if is_spain_offer(offer):
        return True
    for text in (f"{offer.location} {' '.join(offer.tags)}".lower(), offer.summary.lower()):
        if any(marker in text for marker in _NON_EUROPE_MARKERS):
            return False
        if any(marker in text for marker in _EUROPE_MARKERS):
            return True
    return None


def is_spain_offer(offer: JobOffer) -> bool:
    """Whether the offer is based in (or explicitly open to) Spain."""
    source = offer.source.lower()
    if any(marker in source for marker in _SPAIN_SOURCES):
        return True
    text = f"{offer.location} {offer.title} {' '.join(offer.tags)}".lower()
    return any(marker in text for marker in _SPAIN_MARKERS)
