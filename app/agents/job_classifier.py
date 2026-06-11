"""Agent 2 — Job Classifier.

Classifies a job offer into a category, estimates the seniority and assigns it
a relevance score (0-100) using an LLM. If the LLM fails, it falls back to a
keyword-based heuristic so the pipeline does not stall.
"""

from __future__ import annotations

from app.agents.json_utils import extract_json_object
from app.agents.prompts import CLASSIFIER_SYSTEM
from app.core.logging import get_logger
from app.domain.entities import JobOffer
from app.domain.value_objects import Category, RelevanceScore
from app.interfaces.agent import Agent
from app.interfaces.llm import ChatMessage, LLMProvider

logger = get_logger(__name__)

# Markers of low-substance job ads penalized by the fallback heuristic.
_SPAM_MARKERS: tuple[str, ...] = (
    "rockstar",
    "ninja",
    "guru",
    "work hard play hard",
    "gana dinero desde casa",
    "sin experiencia",
    "ingresos extra",
    "unlimited earning",
    "commission only",
)

_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.AI_ML: ("machine learning", " ml ", "llm", "deep learning", "nlp", " ai ", "ia "),
    Category.DATA: ("data engineer", "data scientist", "analytics", "etl", "warehouse"),
    Category.DEVOPS: ("devops", "sre", "kubernetes", "terraform", "mlops", "cloud"),
    Category.FRONTEND: ("frontend", "front-end", "react", "vue", "angular"),
    Category.MOBILE: ("ios", "android", "flutter", "react native", "mobile"),
    Category.FULLSTACK: ("fullstack", "full-stack", "full stack"),
    Category.BACKEND: ("backend", "back-end", "api", "microservice", "python", "java", "go "),
}

_VALID_SENIORITIES = ("junior", "mid", "senior", "lead", "unknown")


class JobClassifierAgent(Agent[JobOffer, JobOffer]):
    """Assigns a category, seniority and relevance to a job offer."""

    name = "job_classifier"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, input_data: JobOffer) -> JobOffer:
        try:
            return await self._classify_with_llm(input_data)
        except Exception as exc:
            logger.warning("classifier.llm_failed", error=str(exc), title=input_data.title)
            return self._classify_with_heuristic(input_data)

    async def _classify_with_llm(self, offer: JobOffer) -> JobOffer:
        user = (
            f"Puesto: {offer.title}\n"
            f"Empresa: {offer.company}\n"
            f"Fuente: {offer.source}\n"
            f"Ubicación: {offer.location or 'no consta'}\n"
            f"Modalidad: {offer.modality.value}\n"
            f"Salario: {offer.salary or 'no consta'}\n"
            f"Etiquetas: {', '.join(offer.tags) or 'ninguna'}\n"
            f"Descripción: {offer.summary}"
        )
        raw = await self._llm.complete_json(
            [
                ChatMessage(role="system", content=CLASSIFIER_SYSTEM),
                ChatMessage(role="user", content=user),
            ],
            temperature=0.0,
            max_tokens=300,
        )
        data = extract_json_object(raw)
        category = Category.from_str(str(data.get("category", "Other")))
        score = RelevanceScore.clamped(float(data.get("relevance_score", 50)))
        seniority = str(data.get("seniority", "unknown")).strip().lower()
        if seniority not in _VALID_SENIORITIES:
            seniority = "unknown"
        logger.info(
            "classifier.classified",
            title=offer.title,
            category=category.value,
            score=score.value,
            seniority=seniority,
        )
        return offer.with_classification(category, score, seniority=seniority)

    def _classify_with_heuristic(self, offer: JobOffer) -> JobOffer:
        text = f" {offer.title} {' '.join(offer.tags)} {offer.summary} ".lower()
        best_category = Category.OTHER
        best_hits = 0
        for category, keywords in _KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > best_hits:
                best_hits, best_category = hits, category
        spam_hits = sum(1 for marker in _SPAM_MARKERS if marker in text)
        # Base score from the number of matches, with a spam penalty and a small
        # bonus for offers that disclose a salary.
        score = RelevanceScore.clamped(
            45 + best_hits * 10 + (5 if offer.salary else 0) - spam_hits * 25
        )
        return offer.with_classification(best_category, score, seniority="unknown")
