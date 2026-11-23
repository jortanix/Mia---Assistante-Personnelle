"""Adaptateur CalDAV iCloud minimal — lecture seule.

La classe :class:`~briefing.caldav.ICloudCalDAVClient` découvre le principal,
l'agenda et les calendriers de l'utilisateur, puis interroge les événements
d'un intervalle via une requête ``REPORT`` ``calendar-query``.

Garanties :
- uniquement des requêtes ``PROPFIND`` (découverte) et ``REPORT`` (lecture) ;
  aucune écriture (``PUT``, ``DELETE``, ``MKCALENDAR``, ``POST``…) n'est jamais
  émise, même en cas d'erreur ;
- authentification par mot de passe applicatif transmise en en-tête HTTPS ;
  les identifiants ne sont jamais journalisés ni inclus dans les erreurs ;
- les événements sont filtrés pour l'intervalle demandé (par défaut : le jour
  courant dans le fuseau de l'utilisateur) : rien n'est indexé ni conservé.

Indépendant de tout calendrier Google : aucune substitution à ``gcalendar``.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from xml.sax.saxutils import unescape as _xml_unescape

import requests
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CalDAVError(Exception):
    """Échec d'une lecture CalDAV (réseau, authentification, réponse invalide)."""


DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"

_Q_DAV_HREF = f"{{{DAV_NS}}}href"
_Q_DAV_PRINCIPAL = f"{{{DAV_NS}}}current-user-principal"
_Q_DAV_CALHOME = f"{{{CALDAV_NS}}}calendar-home-set"
_Q_DAV_DISPLAYNAME = f"{{{DAV_NS}}}displayname"
_Q_DAV_RESOURCETYPE = f"{{{DAV_NS}}}resourcetype"
_Q_DAV_CALENDAR = f"{{{CALDAV_NS}}}calendar"
_Q_DAV_STATUS = f"{{{DAV_NS}}}status"
_Q_DAV_RESPONSE = f"{{{DAV_NS}}}response"
_Q_CALENDAR_DATA = f"{{{CALDAV_NS}}}calendar-data"
_Q_DAV_PROP = f"{{{DAV_NS}}}prop"
_Q_DAV_PROPSTAT = f"{{{DAV_NS}}}propstat"


# ---------------------------------------------------------------------------
# Requêtes XML
# ---------------------------------------------------------------------------

_PF_PRINCIPAL = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:current-user-principal/>
  </d:prop>
</d:propfind>
"""

_PF_CALHOME = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:resourcetype/>
    <c:calendar-home-set/>
  </d:prop>
</d:propfind>
"""

_PF_CALENDARS = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <c:supported-calendar-component-set/>
  </d:prop>
</d:propfind>
"""

_REPORT_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{start}" end="{end}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
  <c:limit>
    <c:nresults>{limit}</c:nresults>
  </c:limit>
</c:calendar-query>
"""

# ---------------------------------------------------------------------------
# Lecteurs XML / iCalendar
# ---------------------------------------------------------------------------


def _find_text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _find_in_props(response: ET.Element, tag: str) -> Optional[ET.Element]:
    """Trouve une propriété imbriquée dans ``propstat/prop`` d'une réponse."""
    for prop in response.iter(_Q_DAV_PROP):
        node = prop.find(tag)
        if node is not None:
            return node
    return None


def _propstat_ok(response: ET.Element) -> bool:
    """Vrai si au moins un ``propstat`` de la réponse annonce un statut 2xx."""
    for propstat in response.findall(_Q_DAV_PROPSTAT):
        status = propstat.find(_Q_DAV_STATUS)
        if status is not None and status.text and "200" in status.text:
            return True
    return False


# --- Fragment iCalendar VEVENT -------------------------------------------------

def _unfold_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _split_property(line: str) -> Tuple[str, Dict[str, str], str]:
    name, _, rest = line.partition(":")
    tokens = name.split(";")
    prop = tokens[0].upper()
    params: Dict[str, str] = {}
    for token in tokens[1:]:
        if "=" in token:
            key, _, value = token.partition("=")
            params[key.upper()] = value
    return prop, params, rest


def _unescape_ical(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _parse_ical_datetime(
    params: Dict[str, str], value: str
) -> Tuple[Optional[datetime], bool]:
    """Convertit une valeur DATE / DATE-TIME iCalendar.

    Retourne ``(datetime, all_day)`` où ``all_day`` est vrai pour les
    valeurs ``DATE`` (journée entière) et faux pour les heures UTC, TZID et
    flottantes. Une valeur illisible renvoie ``(None, all_day)`` sans lever
    d'exception : un événement malformé est alors simplement ignoré.
    """
    value = value.strip()
    all_day = params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value)
    try:
        if all_day:
            return datetime.strptime(value[:8], "%Y%m%d"), True
        if value.endswith("Z"):
            aware = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            return aware, False
        tzid = params.get("TZID", "").strip().strip('"')
        if tzid:
            try:
                zone = ZoneInfo(tzid)
            except ZoneInfoNotFoundError:
                zone = None
            if zone is not None:
                aware = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(
                    tzinfo=zone
                )
                return aware, False
        # Heure flottante : heure murale dans le fuseau local du briefing.
        return datetime.strptime(value, "%Y%m%dT%H%M%S"), False
    except ValueError:
        return None, all_day


def _parse_icalendar(calendar_text: str) -> List[Dict[str, Any]]:
    """Extrait les événements ``VEVENT`` d'un flux iCalendar.

    Retourne une liste de dictionnaires prêts à consommer :
    ``id``, ``summary``, ``description``, ``location``, ``all_day``,
    ``start``/``end`` (ISO, converti si besoin) ainsi que ``_start``/``_end``
    (``datetime`` bruts, pour le filtrage local).
    """
    events: List[Dict[str, Any]] = []
    in_event = False
    current: Dict[str, Any] = {}

    for line in _unfold_lines(calendar_text):
        body = line.strip()
        if body.upper() == "BEGIN:VEVENT":
            in_event = True
            current = {"summary": "", "description": "", "location": ""}
            continue
        if body.upper() == "END:VEVENT":
            if in_event and current.get("summary", ""):
                events.append(current)
            in_event = False
            continue
        if not in_event or not body:
            continue

        prop, params, value = _split_property(body)
        if prop == "UID":
            current["id"] = value.strip()
        elif prop == "SUMMARY":
            current["summary"] = _unescape_ical(value)
        elif prop == "DESCRIPTION":
            current["description"] = _unescape_ical(value)[:4000]
        elif prop == "LOCATION":
            current["location"] = _unescape_ical(value)
        elif prop in ("DTSTART", "DTEND", "DUE"):
            parsed, all_day = _parse_ical_datetime(params, value)
            if parsed is None:
                continue
            current[prop.lower()] = parsed
            if all_day:
                current["all_day"] = True
            if prop == "DUE" and "dtend" not in current:
                current["dtend"] = parsed

    return [_finalize_event(ev) for ev in events]


def _finalize_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    all_day = bool(ev.get("all_day", False))
    start = ev.get("dtstart")
    end = ev.get("dtend")
    if all_day and end is None and start is not None:
        # DTEND est exclusif en iCalendar : une journée entière se termine
        # au lendemain à minuit.
        end = start + timedelta(days=1)

    result: Dict[str, Any] = {
        "id": ev.get("id", ""),
        "summary": ev["summary"],
        "description": ev.get("description", ""),
        "location": ev.get("location", ""),
        "all_day": all_day,
        "_start": ev.get("dtstart"),
        "_end": end,
    }
    result["start"] = _to_iso(result["_start"])
    result["end"] = _to_iso(end)
    return result


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _to_local(dt: Optional[datetime], zone: Any) -> Optional[datetime]:
    """Convertit un ``datetime`` iCalendar dans le fuseau ``zone``.

    Les heures flottantes (naïves) sont interprétées comme des heures
    murales dans le fuseau du briefing ; les heures connues sont converties.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def _overlaps(ev: Dict[str, Any], day_start: datetime, day_end: datetime) -> bool:
    start = ev["_start"]
    if start is None:
        return False
    end = ev["_end"] or start
    zone = day_start.tzinfo
    start = _to_local(start, zone)
    end = _to_local(end, zone)
    return start < day_end and end > day_start


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ICloudCalDAVClient:
    """Client CalDAV iCloud en lecture seule.

    Paramètres
    ----------
    apple_id:
        Adresse du compte iCloud (ex. ``nom@icloud.com``).
    app_password:
        Mot de passe applicatif iCloud (jamais le mot de passe du compte).
    base_url:
        Racine CalDAV (défaut : https://caldav.icloud.com).
    principal_url:
        Éventuel chemin du principal déjà connu (sinon découvert).
    calendar_id:
        Nom d'affichage d'un seul calendrier à interroger (optionnel).
    timezone:
        Fuseau local pour le filtre et l'affichage (défaut : ``Europe/Paris``).
    limit:
        Nombre maximal d'événements remontés par calendrier.
    session:
        Session HTTP injectable (tests).
    """

    def __init__(
        self,
        apple_id: str,
        app_password: str,
        *,
        base_url: str = "https://caldav.icloud.com",
        principal_url: str = "",
        calendar_id: str = "",
        timezone: str = "Europe/Paris",
        limit: int = 200,
        session: Any = None,
    ) -> None:
        if not apple_id or not app_password:
            raise CalDAVError("Identifiants CalDAV manquants.")
        self._apple_id = apple_id
        self._password = app_password
        self._base_url = base_url.rstrip("/")
        self._principal_url = principal_url
        self._calendar_id = calendar_id
        self._timezone = timezone
        self._limit = limit
        self._session = session if session is not None else requests.Session()
        self._calendars: Optional[List[Dict[str, str]]] = None

    def _request(self, method: str, url: str, body: bytes, depth: str) -> str:
        if method not in ("PROPFIND", "REPORT"):
            raise CalDAVError("Méthode non autorisée pour un accès en lecture seule.")
        try:
            response = self._session.request(
                method,
                url,
                data=body,
                headers={
                    "Content-Type": "application/xml; charset=utf-8",
                    "Depth": depth,
                    "Brief": "t",
                },
                auth=(self._apple_id, self._password),
                timeout=(5, 60),
            )
        except (requests.RequestException, OSError) as exc:
            raise CalDAVError("Connexion CalDAV impossible.") from exc
        if response.status_code in (401, 403):
            raise CalDAVError("Authentification iCloud refusée.")
        if response.status_code not in (200, 207):
            raise CalDAVError(f"Réponse CalDAV inattendue ({response.status_code}).")
        return response.text

    # --- découverte -------------------------------------------------------

    def discover_principal(self) -> str:
        """Retourne l'URL du principal (découverte, sinon repli construit)."""
        if self._principal_url:
            return self._principal_url

        candidates = (
            f"{self._base_url}/.well-known/caldav",
            f"{self._base_url}/",
        )
        for url in candidates:
            try:
                xml_text = self._request("PROPFIND", url, _PF_PRINCIPAL, "0")
                root = ET.fromstring(xml_text)
            except (CalDAVError, ET.ParseError):
                continue
            principal_el = next((el for el in root.iter(_Q_DAV_PRINCIPAL)), None)
            href = (
                principal_el.find(_Q_DAV_HREF) if principal_el is not None else None
            )
            if href is not None and href.text and href.text.strip():
                return urljoin(url, href.text.strip())

        # Repli : chemin principal iCloud classique.
        return f"{self._base_url}/{self._apple_id}/principal/"

    def calendar_home(self, principal: str) -> str:
        xml_text = self._request("PROPFIND", principal, _PF_CALHOME, "0")
        root = ET.fromstring(xml_text)
        home_el = next((el for el in root.iter(_Q_DAV_CALHOME)), None)
        href = home_el.find(_Q_DAV_HREF) if home_el is not None else None
        if href is None or not href.text:
            raise CalDAVError("Agenda CalDAV introuvable pour ce principal.")
        return urljoin(principal, href.text.strip())

    def list_calendars(self, calendar_home: str) -> List[Dict[str, str]]:
        xml_text = self._request("PROPFIND", calendar_home, _PF_CALENDARS, "1")
        root = ET.fromstring(xml_text)
        calendars: List[Dict[str, str]] = []
        for response in root.findall(_Q_DAV_RESPONSE):
            resourcetype = _find_in_props(response, _Q_DAV_RESOURCETYPE)
            if resourcetype is None or resourcetype.find(_Q_DAV_CALENDAR) is None:
                continue
            href = _find_text(response, _Q_DAV_HREF)
            display_node = _find_in_props(response, _Q_DAV_DISPLAYNAME)
            displayname = (
                display_node.text.strip()
                if display_node is not None and display_node.text
                else ""
            )
            if href:
                calendars.append(
                    {"href": urljoin(calendar_home, href), "displayname": displayname}
                )
        if self._calendar_id:
            calendars = [
                c for c in calendars if c["displayname"] == self._calendar_id
            ]
        return calendars

    def _get_calendars(self) -> List[Dict[str, str]]:
        if self._calendars is None:
            principal = self.discover_principal()
            home = self.calendar_home(principal)
            self._calendars = self.list_calendars(home)
        return self._calendars

    # --- lecture des événements -------------------------------------------

    def events_overlapping(
        self, day_start: datetime, day_end: datetime
    ) -> List[Dict[str, Any]]:
        """Événements chevauchant ``[day_start, day_end)`` (fuseau local)."""
        if day_start.tzinfo is None:
            day_start = day_start.replace(tzinfo=ZoneInfo(self._timezone))
        if day_end.tzinfo is None:
            day_end = day_end.replace(tzinfo=ZoneInfo(self._timezone))

        start_utc = day_start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = day_end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        body = _REPORT_TEMPLATE.format(start=start_utc, end=end_utc, limit=self._limit).encode("utf-8")

        events: List[Dict[str, Any]] = []
        for calendar in self._get_calendars():
            try:
                raw = self._request("REPORT", calendar["href"], body, "1")
            except CalDAVError:
                continue
            for calendar_data in self._extract_calendar_data(raw):
                for event in _parse_icalendar(calendar_data):
                    if _overlaps(event, day_start, day_end):
                        event["calendar"] = calendar["displayname"] or ""
                        events.append(event)
        zone = ZoneInfo(self._timezone)
        events.sort(
            key=lambda e: _to_local(e.get("_start"), zone)
            or datetime.min.replace(tzinfo=zone)
        )
        for event in events:
            event.pop("_start", None)
            event.pop("_end", None)
        return events

    @staticmethod
    def _extract_calendar_data(xml_text: str) -> List[str]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise CalDAVError("Réponse CalDAV illisible.") from exc

        chunks: List[str] = []
        for response in root.findall(_Q_DAV_RESPONSE):
            if not _propstat_ok(response):
                continue
            data_node = _find_in_props(response, _Q_CALENDAR_DATA)
            if data_node is None or data_node.text is None:
                continue
            payload = data_node.text.strip()
            if not payload:
                continue
            # iCalendar peut être échappé (XML) ou encodé en base64.
            decoded = _xml_unescape(payload)
            if not decoded.lstrip().upper().startswith("BEGIN:"):
                try:
                    serialized = base64.b64decode(decoded, validate=True).decode(
                        "utf-8", errors="replace"
                    )
                    if serialized.lstrip().upper().startswith("BEGIN:"):
                        decoded = serialized
                except (binascii.Error, ValueError):
                    pass
            if decoded.lstrip().upper().startswith("BEGIN:"):
                chunks.append(decoded)
        return chunks


__all__ = ["CalDAVError", "ICloudCalDAVClient"]
