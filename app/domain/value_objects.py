"""Domain value objects.

They are immutable and have no identity of their own: they represent business
concepts (a job offer's category, its work modality, a relevance score, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    """Categories into which a job offer is classified."""

    AI_ML = "AI/ML"
    DATA = "Data"
    BACKEND = "Backend"
    FRONTEND = "Frontend"
    FULLSTACK = "Fullstack"
    DEVOPS = "DevOps/Cloud"
    MOBILE = "Mobile"
    OTHER = "Other"

    @classmethod
    def from_str(cls, raw: str) -> Category:
        """Normalize an arbitrary string (e.g. from an LLM) to a valid category."""
        normalized = raw.strip().lower().replace("_", " ").replace("-", " ")
        compact = normalized.replace("/", "").replace(" ", "")
        for member in cls:
            if member.value.lower().replace("/", "").replace(" ", "") == compact:
                return member
        # Common synonyms returned by the models or the sources.
        aliases = {
            "ai": cls.AI_ML,
            "ml": cls.AI_ML,
            "machine learning": cls.AI_ML,
            "artificial intelligence": cls.AI_ML,
            "nlp": cls.AI_ML,
            "llm": cls.AI_ML,
            "data science": cls.DATA,
            "data engineering": cls.DATA,
            "analytics": cls.DATA,
            "back end": cls.BACKEND,
            "front end": cls.FRONTEND,
            "full stack": cls.FULLSTACK,
            "devops": cls.DEVOPS,
            "cloud": cls.DEVOPS,
            "mlops": cls.DEVOPS,
            "sre": cls.DEVOPS,
            "ios": cls.MOBILE,
            "android": cls.MOBILE,
        }
        return aliases.get(normalized, cls.OTHER)


class Modality(StrEnum):
    """Work modality of a job offer."""

    REMOTE = "Remote"
    HYBRID = "Hybrid"
    ONSITE = "Onsite"
    UNKNOWN = "Unknown"

    @classmethod
    def from_str(cls, raw: str) -> Modality:
        """Normalize an arbitrary string (LLM/source) to a valid modality."""
        normalized = raw.strip().lower()
        aliases = {
            "remote": cls.REMOTE,
            "remoto": cls.REMOTE,
            "teletrabajo": cls.REMOTE,
            "full remote": cls.REMOTE,
            "hybrid": cls.HYBRID,
            "híbrido": cls.HYBRID,
            "hibrido": cls.HYBRID,
            "onsite": cls.ONSITE,
            "on-site": cls.ONSITE,
            "presencial": cls.ONSITE,
            "office": cls.ONSITE,
        }
        return aliases.get(normalized, cls.UNKNOWN)


@dataclass(frozen=True, slots=True)
class RelevanceScore:
    """Relevance score bounded to the range [0, 100]."""

    value: int

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 100:
            raise ValueError(f"RelevanceScore debe estar en [0, 100], recibido {self.value}")

    def is_at_least(self, threshold: int) -> bool:
        return self.value >= threshold

    @classmethod
    def clamped(cls, value: float) -> RelevanceScore:
        """Create a score by clamping the value to the valid range."""
        return cls(int(max(0, min(100, round(value)))))
