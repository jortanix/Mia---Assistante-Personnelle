"""Rendu déterministe français du briefing.

Le texte est généré à partir des données structurées sans aucun appel LLM :
il reste la référence en cas de panne du moteur local. Le contenu des mails
n'y figure que comme source à résumer, jamais comme instruction.

On distingue toujours « aucun événement / aucun mail » (source ``ok`` mais
vide) d'une source indisponible ou non configurée.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from zoneinfo import ZoneInfo

from .collect import NOCONFIG, UNAVAILABLE

_WEEKDAYS = (
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
)
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

_MAX_EMAILS_RENDERED = 5


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _local(dt: Optional[datetime], zone: ZoneInfo) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def _day_label(day_iso: str, zone: ZoneInfo) -> str:
    try:
        day = date.fromisoformat(day_iso)
    except ValueError:
        return day_iso
    weekday = _WEEKDAYS[day.weekday()]
    month = _MONTHS[day.month - 1]
    return f"{weekday} {day.day} {month} {day.year}"


def _format_sender(sender: str) -> str:
    if not sender:
        return ""
    clean = sender.strip().splitlines()[0].strip()
    if "<" in clean:
        display = clean.split("<")[0].strip().strip('"')
        if display:
            return display
    return clean


def _format_event(event: Dict[str, Any], zone: ZoneInfo) -> str:
    summary = event.get("summary", "").strip() or "Événement sans titre"
    location = event.get("location", "")
    if event.get("all_day"):
        line = f"Toute la journée — {summary}"
    else:
        start = _local(_parse_iso(event.get("start")), zone)
        if start is not None:
            prefix = start.strftime("%H:%M")
            line = f"{prefix}  {summary}"
        else:
            line = f"—  {summary}"
    if location:
        line += f" ({location})"
    return line


def _render_calendar(calendar: Dict[str, Any], zone: ZoneInfo) -> str:
    status = calendar.get("status")
    if status == NOCONFIG:
        return "Agenda : non configuré (aucun identifiant iCloud fourni)."
    if status == UNAVAILABLE:
        return "Agenda : indisponible pour le moment."
    events = calendar.get("events") or []
    lines = ["Agenda :"]
    if not events:
        lines.append("· Aucun rendez-vous prévu aujourd'hui.")
    else:
        lines.extend(f"· {_format_event(event, zone)}" for event in events)
    return "\n".join(lines)


def _render_emails(emails: Dict[str, Any], zone: ZoneInfo) -> str:
    status = emails.get("status")
    if status == NOCONFIG:
        return "Mails : non configurés (aucun identifiant iCloud fourni)."
    if status == UNAVAILABLE:
        return "Mails : indisponibles pour le moment."
    messages = emails.get("messages") or []
    lines = []
    if not messages:
        lines.append("Mails récents : aucun dans la fenêtre choisie.")
        return lines[0]
    lines.append(f"Mails récents ({len(messages)}) :")
    for message in messages[: _MAX_EMAILS_RENDERED]:
        subject = (message.get("subject") or "").strip() or "(sans objet)"
        sender = _format_sender(message.get("from", ""))
        unread = " [non lu]" if message.get("unread") else ""
        stamp = _mail_stamp(message.get("date"), zone)
        line = f"· {stamp}  {subject}"
        if sender:
            line += f" — de {sender}"
        lines.append(line + unread)
    return "\n".join(lines)


def _mail_stamp(value: Optional[str], zone: ZoneInfo) -> str:
    dt = _parse_iso(value)
    if dt is None:
        return "—"
    dt = _local(dt, zone)
    today = datetime.now(zone).date()
    if dt.date() == today:
        return dt.strftime("%H:%M")
    return dt.strftime("%d/%m")


def render_briefing(payload: Dict[str, Any]) -> str:
    """Produit le texte déterministe français du briefing."""
    zone = ZoneInfo(payload.get("timezone") or "UTC")
    day = payload.get("day", "")
    title = f"Point sur ta journée — {_day_label(day, zone)}"

    sections = [_render_calendar(payload.get("calendar") or {}, zone)]
    sections.append(_render_emails(payload.get("emails") or {}, zone))
    if payload.get("partial"):
        sections.append(
            "Certaines sources étaient indisponibles : ce point est partiel."
        )
    return "\n\n".join([title, *sections])


__all__ = ["render_briefing"]
