"""Per-category accent colors for the Discord embeds.

Centralized so any future output channel reuses the exact same color for a
given category, keeping the brand consistent across surfaces.
"""

from __future__ import annotations

# Per-category colors as integers (the form `discord.Embed(color=...)` expects).
CATEGORY_COLORS: dict[str, int] = {
    "AI/ML": 0x2563EB,  # blue-600 (Anfaia primary)
    "Data": 0x6366F1,  # indigo-500
    "Backend": 0x16A34A,  # green-600
    "Frontend": 0xF59E0B,  # amber-500
    "Fullstack": 0x0D9488,  # teal-600
    "DevOps/Cloud": 0xEB459E,  # pink
    "Mobile": 0x7C3AED,  # violet-600
    "Other": 0x64748B,  # slate-500
}

# Fallback when a category has no explicit color (Anfaia primary blue).
DEFAULT_COLOR = 0x2563EB


def category_color(category_value: str) -> int:
    """Return the integer color for a category value, or the default."""
    return CATEGORY_COLORS.get(category_value, DEFAULT_COLOR)
