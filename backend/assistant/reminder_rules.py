"""Commandes de rappel explicites ; aucun appel IA supplémentaire.

Détecte les demandes du type « rappelle-moi de … dans 1 heure / à 18h /
demain à 9h » et retourne une structure uniforme contenant le titre du
rappel et l'expression de temps brute (``when``), interprétée côté app.
"""

import re


class InvalidReminderRequest(ValueError):
    pass


_REMINDER_PREFIX = re.compile(
    r"""
    ^(?:
        (?:tu\s+|me\s+|moi\s+|toi\s+|nous\s+)?
        (?:r[ée]veill(?:e|es|er|era|eras|ais)
          |rappel(?:l(?:e|es|er|era|eras|ais)|er|ais|e|es|a))
        [- ]?
        (?:moi|toi|nous|me)?
        \s*
        (?:de\s+|d'|à\s+|sur\s+|pour\s+|:)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Expressions de temps, ancrées en fin de phrase. L'ordre de l'alternance
# compte : « demain à 9h » doit être capturé (avec « demain ») avant « à 9h ».
_TIME_HINT = re.compile(
    r"""
    (?P<hint>
        (?:après-demain|apres-demain|demain)\s*(?:(?:matin|midi|soir))?\s*
          (?:[àa]\s+\d{1,2}(?:[hH]:?\d{0,2}|:\d{2}|\s*heures?))?
      | ce\s+(?:soir|matin)
      | dans\s+\d+\s*(?:min|mn|minute|minutes|heure|heures|h|jour|jours)
      | [àa]\s+(?:midi|minuit)
      | [àa]\s+\d{1,2}(?:[hH]\d{0,2}|:\d{2}|\s*heures?)
    )\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_reminder_request(message):
    """Analyse une demande de rappel explicite.

    Retourne :
    - {"action": "none"}
    - {"action": "create_reminder", "data": {"title": ..., "when": ...}}

    Lève InvalidReminderRequest si la demande est incompréhensible
    (titre vide ou trop long).
    """
    if not isinstance(message, str):
        return {"action": "none"}
    text = message.strip().replace("’", "'")
    text = re.sub(r"^mia\s*,\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^peux-tu\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[.!?]+\s*$", "", text)

    match = _TIME_HINT.search(text)
    if match is None:
        return {"action": "none"}

    title = text[: match.start()].strip().lstrip(':').strip()

    # Commande impérative obligatoire : « je pense à rappeler… » n'est pas
    # une demande explicite de rappel.
    prefix = _REMINDER_PREFIX.match(title)
    if prefix is None:
        return {"action": "none"}
    title = title[prefix.end():].strip().lstrip(':').strip()
    # Reste de connecteur isolé (« Rappelle-moi de dans 1 heure » → « de »).
    title = re.sub(r"^(?:de\b|d'|à\b|sur\b|pour\b|:)\s*", "", title).strip()
    title = title.rstrip('.').strip()

    if not title:
        # « Réveille-moi à 7h » : pas de contenu, mais une vraie demande.
        if re.search(r"r[ée]veill", text, flags=re.IGNORECASE):
            title = "Réveil"
        else:
            raise InvalidReminderRequest(
                "Précise ce que je dois te rappeler : rappelle-moi de …"
            )

    if len(title) > 200:
        raise InvalidReminderRequest("Le titre du rappel doit faire au maximum 200 caractères.")
    if '\n' in title or '\r' in title:
        raise InvalidReminderRequest("Écris ta demande sur une seule ligne.")

    hint = match.group("hint").strip()
    return {
        "action": "create_reminder",
        "data": {"title": title, "when": hint},
    }
