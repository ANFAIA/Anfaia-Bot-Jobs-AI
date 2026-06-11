"""Builds the Discord embed from a publishable job offer.

Isolating rendering from sending allows testing the format without touching the
network and reusing it if other channels are published to in the future.
"""

from __future__ import annotations

import discord

from app.domain.category_colors import category_color
from app.domain.entities import PublishableJobOffer
from app.domain.value_objects import Modality

_MAX_FIELD = 1024  # Discord limit per embed field

_MODALITY_LABELS = {
    Modality.REMOTE: "🌍 Remoto",
    Modality.HYBRID: "🏠 Híbrido",
    Modality.ONSITE: "🏢 Presencial",
    Modality.UNKNOWN: "",
}


def _field(value: str) -> str:
    value = value.strip() or "—"
    return value[: _MAX_FIELD - 1] + "…" if len(value) > _MAX_FIELD else value


def build_job_embed(post: PublishableJobOffer) -> discord.Embed:
    """Create the embed using the Anfaia Jobs AI format."""
    offer = post.offer
    edited = post.edited
    color = category_color(post.category.value)

    embed = discord.Embed(
        title=f"💼 {edited.title}",
        url=edited.source_url,
        color=color,
    )
    embed.set_author(name="Oferta de empleo · Anfaia Jobs AI")
    if offer.company:
        embed.add_field(name="🏢 Empresa", value=_field(offer.company), inline=True)
    location = " · ".join(
        part for part in (_MODALITY_LABELS[offer.modality], offer.location) if part
    )
    if location:
        embed.add_field(name="📍 Ubicación", value=_field(location), inline=True)
    if offer.salary:
        embed.add_field(name="💰 Salario", value=_field(offer.salary), inline=True)
    embed.add_field(name="🛠️ Qué harías", value=_field(edited.role_summary), inline=False)
    embed.add_field(name="✅ Qué piden", value=_field(edited.requirements), inline=False)
    embed.add_field(name="📋 Condiciones", value=_field(edited.conditions), inline=False)
    embed.add_field(
        name="💡 Por qué puede interesarte",
        value=_field(edited.why_interesting),
        inline=False,
    )
    embed.add_field(name="🔗 Oferta original", value=edited.source_url, inline=False)
    seniority = f" · {post.offer.seniority}" if post.offer.seniority not in ("", "unknown") else ""
    embed.set_footer(
        text=f"{post.category.value}{seniority} · relevancia {post.relevance_score.value}/100 · "
        f"{offer.source}"
    )
    return embed
