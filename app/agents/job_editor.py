"""Agent 4 — Job Editor.

Transforms a job offer into an edited job post for Discord, structured into
clear sections (role, requirements, conditions, fit). It uses the LLM and, if
it fails, generates a minimal version from the offer itself so as not to block
publication.
"""

from __future__ import annotations

from app.agents.json_utils import extract_json_object
from app.agents.prompts import EDITOR_SYSTEM
from app.core.logging import get_logger
from app.domain.entities import EditedJobPost, JobOffer
from app.interfaces.agent import Agent
from app.interfaces.llm import ChatMessage, LLMProvider

logger = get_logger(__name__)


class JobEditorAgent(Agent[JobOffer, EditedJobPost]):
    """Edits and structures a job offer for the community."""

    name = "job_editor"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, input_data: JobOffer) -> EditedJobPost:
        try:
            return await self._edit_with_llm(input_data)
        except Exception as exc:
            logger.warning("editor.llm_failed", error=str(exc), title=input_data.title)
            return self._fallback(input_data)

    async def _edit_with_llm(self, offer: JobOffer) -> EditedJobPost:
        content = offer.raw_content or offer.summary
        user = (
            f"Categoría: {offer.category.value if offer.category else 'Other'}\n"
            f"Puesto: {offer.title}\n"
            f"Empresa: {offer.company}\n"
            f"Fuente: {offer.source}\n"
            f"URL: {offer.url}\n"
            f"Ubicación: {offer.location or 'no consta'}\n"
            f"Modalidad: {offer.modality.value}\n"
            f"Salario: {offer.salary or 'no consta'}\n"
            f"Seniority estimado: {offer.seniority or 'unknown'}\n"
            f"Etiquetas: {', '.join(offer.tags) or 'ninguna'}\n"
            f"Descripción: {content}"
        )
        raw = await self._llm.complete_json(
            [
                ChatMessage(role="system", content=EDITOR_SYSTEM),
                ChatMessage(role="user", content=user),
            ],
            temperature=0.4,
            max_tokens=700,
        )
        data = extract_json_object(raw)
        edited = EditedJobPost(
            title=str(data.get("title") or f"{offer.title} — {offer.company}").strip()[:256],
            role_summary=str(data.get("role_summary", "")).strip(),
            requirements=str(data.get("requirements", "")).strip(),
            conditions=str(data.get("conditions", "")).strip(),
            why_interesting=str(data.get("why_interesting", "")).strip(),
            source_url=offer.url,
        )
        logger.info("editor.edited", title=edited.title)
        return edited

    @staticmethod
    def _fallback(offer: JobOffer) -> EditedJobPost:
        conditions_parts = [
            part
            for part in (
                offer.salary and f"Salario: {offer.salary}",
                offer.modality.value != "Unknown" and f"Modalidad: {offer.modality.value}",
                offer.location and f"Ubicación: {offer.location}",
            )
            if part
        ]
        return EditedJobPost(
            title=f"{offer.title} — {offer.company}"[:256],
            role_summary=offer.summary or "Sin descripción disponible.",
            requirements="Consulta los requisitos en el anuncio original.",
            conditions="; ".join(conditions_parts) or "Condiciones no especificadas.",
            why_interesting="Ficha automática: revisa la oferta original para valorar el encaje.",
            source_url=offer.url,
        )
