"""Collecte du briefing (agenda + mails) et états de disponibilité.

Chaque source (calendrier, mails) porte un statut :

- ``ok`` — les données ont été lues (éventuellement vides : c'est la
  différence d'avec une source inaccessible) ;
- ``unavailable`` — la source n'a pas pu être jointe ou l'authentification a
  échoué (on indique pourquoi sans révéler de secret) ;
- ``not_configured`` — aucun identifiant iCloud n'est configuré.

L'ensemble est marqué ``partial`` quand au moins une source n'est pas ``ok``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .caldav import CalDAVError, ICloudCalDAVClient
from .config import BriefingConfig
from .imap import IMAPError, ICloudIMAPClient

logger = logging.getLogger(__name__)

NOCONFIG = "not_configured"
UNAVAILABLE = "unavailable"
OK = "ok"


def resolve_timezone(name: str) -> ZoneInfo:
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Fuseau inconnu %r, repli sur UTC.", name)
        return ZoneInfo("UTC")


class BriefingCollector:
    """Orchestre la collecte du briefing (sources injectables pour les tests)."""

    def __init__(
        self,
        config: BriefingConfig,
        *,
        calendar_client: Optional[ICloudCalDAVClient] = None,
        imap_client: Optional[ICloudIMAPClient] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self._config = config
        self._calendar = calendar_client
        self._imap = imap_client
        self._now = now

    def _current_time(self) -> datetime:
        if self._now is not None:
            now = self._now
        else:
            now = datetime.now(self.resolve_tz())
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.resolve_tz())
        return now

    def resolve_tz(self) -> ZoneInfo:
        return resolve_timezone(self._config.timezone)

    def collect(self) -> Dict[str, Any]:
        zone = self.resolve_tz()
        now = self._current_time()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        calendar_status, events = self._collect_calendar(day_start, day_end)
        email_status, messages = self._collect_emails(now)

        partial = any(status != OK for status in (calendar_status, email_status))

        return {
            "day": day_start.date().isoformat(),
            "timezone": zone.key,
            "generated_at": now.isoformat(),
            "calendar": {"status": calendar_status, "events": events},
            "emails": {"status": email_status, "messages": messages},
            "partial": partial,
        }

    # --- sources ----------------------------------------------------------

    def _collect_calendar(
        self, day_start: datetime, day_end: datetime
    ) -> tuple[str, List[Dict[str, Any]]]:
        if not self._config.configured or self._calendar is None:
            return NOCONFIG, []
        try:
            events = self._calendar.events_overlapping(day_start, day_end)
            return OK, events
        except CalDAVError as exc:
            logger.warning("Calendrier iCloud inaccessible : %s", exc)
            return UNAVAILABLE, []
        except Exception as exc:  # défensif : jamais de secret dans l'erreur
            logger.warning("Lecture du calendrier impossible : %s", exc)
            return UNAVAILABLE, []

    def _collect_emails(self, now: datetime) -> tuple[str, List[Dict[str, Any]]]:
        if not self._config.configured or self._imap is None:
            return NOCONFIG, []
        try:
            messages = self._imap.recent_messages(now)
            return OK, messages
        except IMAPError as exc:
            logger.warning("Mails iCloud inaccessibles : %s", exc)
            return UNAVAILABLE, []
        except Exception as exc:  # défensif : jamais de secret dans l'erreur
            logger.warning("Lecture des mails impossible : %s", exc)
            return UNAVAILABLE, []


__all__ = ["BriefingCollector", "OK", "UNAVAILABLE", "NOCONFIG", "resolve_timezone"]
