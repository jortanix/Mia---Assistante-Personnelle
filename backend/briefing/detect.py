"""Détection de la commande « Fais-moi le point sur ma journée ».

Déterministe et sans LLM : le texte est replié (minuscules, accents ôtés)
puis comparé à des formulations connues. Cette fonction décide seulement si
le message de chat déclenche le briefing automatique ; elle ne fait aucune
lecture de données.
"""

from __future__ import annotations

import unicodedata

# Indices portant sur le « jour » ou l'organisation de la journée.
_DAY_HINTS = (
    "journee",
    "aujourdhui",
    "jour",
    "agenda",
    "planning",
    "calendrier",
    "rendezvous",
    "briefing",
    "matinee",
    "apresmidi",
    "soiree",
)

# Formulations centrées sur « le point ».
_POINT_PATTERNS = (
    "point sur",
    "point du jour",
    "point de la journee",
    "point de mon",
    "point de ma journee",
    "point de nos",
    "point de ta journee",
)


def _fold(text: str) -> str:
    """Minuscules, sans accents (base ASCII), sans caractères spéciaux demandés."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def is_daily_briefing_request(text: str) -> bool:
    """Vrai si ``text`` ressemble à une demande de point sur la journée."""
    folded = _fold(text or "")
    if not folded:
        return False
    if not any(hint in folded for hint in _DAY_HINTS):
        return False
    if "briefing" in folded:
        return True
    return any(pattern in folded for pattern in _POINT_PATTERNS)


__all__ = ["is_daily_briefing_request"]
