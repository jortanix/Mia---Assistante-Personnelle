"""Commandes de rappel explicites ; aucun appel IA supplémentaire.

Détecte les demandes du type « rappelle-moi de … dans 1 heure / à 18h /
demain à 9h » et retourne une structure uniforme contenant le titre du
rappel et l'expression de temps brute (``when``). ``interpret_when``
convertit ensuite cette expression en date d'échéance : l'assistant agit
directement, sans confirmation de l'utilisateur.
"""

import re
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo


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


def interpret_when(hint, now=None, tz=None):
    """Convertit une expression de temps brute en ``datetime`` future.

    - « dans 1 heure / 30 minutes / 2 jours » -> décalage relatif ;
    - « à 18h30 », « à 18h », « 18 h » -> aujourd'hui, demain si dépassé ;
    - « demain [à 9h] », « après-demain », « ce soir », « ce matin »,
      « cet après-midi », « à midi », « à minuit ».
    - sinon (incompréhensible) : maintenant + 1 heure.

    Retourne toujours une date (heure locale de l'utilisateur), jamais None.
    """
    if tz is None:
        tz = ZoneInfo(settings.BRIEFING_TIME_ZONE)
    if now is None:
        now = timezone.now().astimezone(tz)
    elif now.tzinfo is None:
        now = timezone.make_aware(now, tz)

    text = hint.strip().lower().replace("’", "'")
    now_date = now.date()

    # « dans X minutes / heures / jours »
    m = re.search(r"dans\s+(\d+)\s*(min|mn|minute|minutes|heure|heures|h|jour|jours)", text)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("jour"):
            delta = timedelta(days=amount)
        elif unit.startswith("h"):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(minutes=amount)
        return now + delta

    def at(day, hour, minute=0):
        return timezone.make_aware(datetime.combine(day, time(hour, minute)), tz)

    # Jour cible. L'ordre compte : « après-demain » avant « demain ».
    day_offset = 0
    default_hour = None
    if "après-demain" in text or "apres-demain" in text:
        day_offset = 2
        default_hour = 9
    elif "demain" in text:
        day_offset = 1
        default_hour = 9
    elif "ce soir" in text:
        default_hour = 20
    elif "cet après-midi" in text or "cet apres-midi" in text:
        default_hour = 15
    elif "ce matin" in text:
        default_hour = 9

    # Heures particulières (attention à ne pas confondre « midi » et
    # « après-midi »).
    if "minuit" in text:
        candidate = at(now_date + timedelta(days=day_offset), 0)
    elif re.search(r"(?<!-)midi\b", text):
        candidate = at(now_date + timedelta(days=day_offset), 12)
    else:
        clock = re.search(r"(\d{1,2})\s*[h:]\s*(\d{1,2})?", text)
        hour = minute = None
        if clock:
            h, mm = int(clock.group(1)), int(clock.group(2) or 0)
            if h <= 23 and mm <= 59:
                hour, minute = h, mm
        if hour is not None:
            candidate = at(now_date + timedelta(days=day_offset), hour, minute)
            # « à 18h » demandé à 21h désigne probablement demain.
            if candidate <= now:
                candidate = at(now_date + timedelta(days=day_offset + 1), hour, minute)
        elif default_hour is not None:
            candidate = at(now_date + timedelta(days=day_offset), default_hour)
            # « ce soir » demandé à 23h vise demain.
            if candidate <= now:
                candidate = at(now_date + timedelta(days=day_offset + 1), default_hour)
        else:
            return now + timedelta(hours=1)

    return candidate
