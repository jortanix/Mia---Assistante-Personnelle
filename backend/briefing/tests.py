"""Tests du briefing iCloud : parseurs, lecture seule, statuts, rendu, API.

Les tests réseau utilisent des sessions / connexions factices : aucune
donnée réelle n'est lue, aucun secret n'est requis.
"""

import base64
import json
import logging
import unittest

logging.getLogger("briefing.collect").setLevel(logging.CRITICAL)
from datetime import datetime
from email.message import EmailMessage
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from briefing import caldav, collect, imap, render as brief_render
from briefing.caldav import CalDAVError, ICloudCalDAVClient
from briefing.collect import BriefingCollector
from briefing.config import BriefingConfig
from briefing.detect import is_daily_briefing_request
from briefing.imap import IMAPError, ICloudIMAPClient

PARIS = ZoneInfo("Europe/Paris")


# ---------------------------------------------------------------------------
# iCalendar (unités)
# ---------------------------------------------------------------------------

class ICalendarParseTests(unittest.TestCase):
    def test_timed_tzid_event(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev1\n"
            "DTSTART;TZID=Europe/Paris:20261120T090000\n"
            "DTEND;TZID=Europe/Paris:20261120T100000\n"
            "SUMMARY:Réunion d'équipe\n"
            "LOCATION:Salle A\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        events = caldav._parse_icalendar(ical)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["summary"], "Réunion d'équipe")
        self.assertEqual(ev["location"], "Salle A")
        self.assertFalse(ev["all_day"])
        self.assertEqual(ev["start"], "2026-11-20T09:00:00+01:00")

    def test_all_day_event(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev2\n"
            "DTSTART;VALUE=DATE:20261120\n"
            "DTEND;VALUE=DATE:20261121\n"
            "SUMMARY:Congés\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        events = caldav._parse_icalendar(ical)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertTrue(ev["all_day"])
        self.assertEqual(ev["start"], "2026-11-20T00:00:00")
        self.assertEqual(ev["end"], "2026-11-21T00:00:00")

    def test_utc_event_conversion(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev3\n"
            "DTSTART:20261120T130000Z\n"
            "DTEND:20261120T140000Z\n"
            "SUMMARY:Visio\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        ev = caldav._parse_icalendar(ical)[0]
        self.assertEqual(ev["start"], "2026-11-20T13:00:00+00:00")

    def test_floating_time_is_not_all_day(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev4\n"
            "DTSTART:20261120T140000\n"
            "DTEND:20261120T150000\n"
            "SUMMARY:Flottant\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        ev = caldav._parse_icalendar(ical)[0]
        self.assertFalse(ev["all_day"])
        self.assertEqual(ev["start"], "2026-11-20T14:00:00")

    def test_escaped_summary(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev5\n"
            "DTSTART:20261120T090000Z\n"
            "SUMMARY:Point \\, virgule \\; slash \\\\ fin\\nsuite\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        self.assertEqual(
            caldav._parse_icalendar(ical)[0]["summary"],
            "Point , virgule ; slash \\ fin\nsuite",
        )

    def test_malformed_date_ignored(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev6\n"
            "DTSTART:PASUNEHEURE\n"
            "SUMMARY:Sans horaire\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        events = caldav._parse_icalendar(ical)
        # L'événement ne casse pas la lecture mais n'a aucun horaire fiable :
        # il sera écarté du filtrage par journée.
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["start"])

    def test_unknown_tzid_falls_back_to_floating(self):
        ical = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:ev7\n"
            "DTSTART;TZID=Zone/Inconnue:20261120T090000\n"
            "SUMMARY:Fuseau inconnu\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        ev = caldav._parse_icalendar(ical)[0]
        self.assertFalse(ev["all_day"])
        self.assertIsNotNone(ev["start"])
        self.assertNotIn("+", ev["start"])


# ---------------------------------------------------------------------------
# Client CalDAV (session factice)
# ---------------------------------------------------------------------------

_PF_PRINCIPAL = (
    '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href>'
    "<d:propstat><d:prop><d:current-user-principal><d:href>/principal/</d:href>"
    "</d:current-user-principal></d:prop><d:status>HTTP/1.1 200 OK</d:status>"
    "</d:propstat></d:response></d:multistatus>"
)
_PF_CALHOME = (
    '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:response><d:href>/principal/</d:href><d:propstat><d:prop>"
    "<c:calendar-home-set><d:href>/calendars/</d:href></c:calendar-home-set>"
    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    "</d:multistatus>"
)
_PF_CALS = (
    '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:response><d:href>/calendars/cal1/</d:href><d:propstat><d:prop>"
    "<d:displayname>Perso</d:displayname><d:resourcetype><c:calendar/>"
    "</d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status>"
    "</d:propstat></d:response></d:multistatus>"
)

_ICAL_TWO_EVENTS = (
    "BEGIN:VCALENDAR\n"
    "BEGIN:VEVENT\n"
    "UID:ev1\n"
    "DTSTART;TZID=Europe/Paris:20261120T090000\n"
    "DTEND;TZID=Europe/Paris:20261120T100000\n"
    "SUMMARY:Reunion equipe\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:ev2\n"
    "DTSTART;TZID=Europe/Paris:20261121T090000\n"
    "DTEND;TZID=Europe/Paris:20261121T100000\n"
    "SUMMARY:Demain\n"
    "END:VEVENT\n"
    "END:VCALENDAR\n"
)


def _multistatus_reply(payloads):
    """Assemble une réponse multistatus CalDAV avec ``calendar-data``."""
    chunks = []
    for payload, href in payloads:
        chunks.append(
            "<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
            "<c:calendar-data>{data}</c:calendar-data></d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>".format(
                href=href, data=payload
            )
        )
    return (
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + "".join(chunks)
        + "</d:multistatus>"
    )


class _HTTPResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code


class FakeCalDAVSession:
    """Session d'appelables CalDAV : valide, lisible, jamais d'écriture.

    ``on_report`` peut lever une exception pour simuler une panne serveur.
    """

    def __init__(self, calendar_data=_ICAL_TWO_EVENTS, *, report_error=None):
        self.calls = []
        self.calendar_data = calendar_data
        self.report_error = report_error

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        body = kwargs.get("data", b"")
        if method == "PROPFIND":
            if b"current-user-principal" in body:
                return _HTTPResponse(_PF_PRINCIPAL)
            if b"calendar-home-set" in body:
                return _HTTPResponse(_PF_CALHOME)
            return _HTTPResponse(_PF_CALS)
        if method == "REPORT":
            if self.report_error is not None:
                raise self.report_error
            payload = base64.b64encode(
                self.calendar_data.encode("utf-8")
            ).decode("ascii")
            return _HTTPResponse(_multistatus_reply([(payload, "/calendars/cal1/ev")]))
        raise AssertionError(f"méthode d'écriture non autorisée : {method}")


class CalDAVClientTests(unittest.TestCase):
    def _client(self, **kwargs):
        session = FakeCalDAVSession()
        client = ICloudCalDAVClient(
            "u@icloud.com", "app-pass", session=session, **kwargs
        )
        return client, session

    def test_readonly_methods_only(self):
        client, session = self._client()
        start = datetime(2026, 11, 20, tzinfo=PARIS)
        client.events_overlapping(start, start.replace(hour=23, minute=59))
        methods = {method for method, _url in session.calls}
        self.assertTrue(methods <= {"PROPFIND", "REPORT"})

    def test_events_filtered_to_the_day(self):
        client, _ = self._client()
        start = datetime(2026, 11, 20, tzinfo=PARIS)
        events = client.events_overlapping(start, start.replace(hour=23, minute=59))
        self.assertEqual([e["summary"] for e in events], ["Reunion equipe"])
        self.assertEqual(events[0]["calendar"], "Perso")

    def test_calendar_href_resolved_absolutely(self):
        client, session = self._client()
        start = datetime(2026, 11, 20, tzinfo=PARIS)
        client.events_overlapping(start, start.replace(hour=23, minute=59))
        report_urls = [url for m, url in session.calls if m == "REPORT"]
        self.assertTrue(
            report_urls and report_urls[0].startswith("https://caldav.icloud.com/")
        )

    def test_auth_refused(self):
        class Refused(FakeCalDAVSession):
            def request(self, method, url, **kwargs):
                return _HTTPResponse("", status_code=401)

        client = ICloudCalDAVClient("u@icloud.com", "mauvais", session=Refused())
        start = datetime(2026, 11, 20, tzinfo=PARIS)
        with self.assertRaises(CalDAVError):
            client.events_overlapping(start, start.replace(hour=23, minute=59))

    def test_server_error_reports_unavailable(self):
        session = FakeCalDAVSession(report_error=OSError("connexion"))
        client = ICloudCalDAVClient("u@icloud.com", "app-pass", session=session)
        start = datetime(2026, 11, 20, tzinfo=PARIS)
        # Les erreurs rapportées par calendrier sont avalées : pas d'événement.
        self.assertEqual(
            client.events_overlapping(start, start.replace(hour=23, minute=59)), []
        )


# ---------------------------------------------------------------------------
# IMAP (connexion factice)
# ---------------------------------------------------------------------------

def _make_email(uid, subject, sender, body, unread=True):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Date"] = f"Thu, 20 Nov 2026 0{uid}:00:00 +0100"
    msg.set_content(body)
    raw = msg.as_bytes()
    # Même forme aplatie que la réponse réelle d'imaplib pour un FETCH.
    return [
        (f"{uid} (BODY[] {{{len(raw)}}}".encode("ascii"), raw),
        b")",
    ]


class FakeIMAP:
    """Connexion IMAP factice : lecture seule, commandes journalisées."""

    def __init__(self, uids, unseen, messages):
        self.uids = uids
        self.unseen = set(unseen)
        self.messages = messages  # dict uid -> liste de réponses FETCH
        self.log = []
        self._select_called = None

    def login(self, user, password):
        self.log.append(("login",))
        return ("OK", [])

    def select(self, mailbox, readonly=False):
        self.log.append(("select", mailbox, readonly))
        self._select_called = (mailbox, readonly)
        return ("OK", [b"1"])

    def uid(self, verb, *args):
        self.log.append(("uid", verb) + tuple(str(a) if isinstance(a, bytes) else a for a in args))
        if verb.upper() == "SEARCH":
            criterion = str(args[-1])
            if criterion == "UNSEEN":
                return ("OK", [b" ".join(str(u).encode() for u in sorted(self.unseen))])
            return ("OK", [b" ".join(str(u).encode() for u in self.uids)])
        if verb.upper() == "FETCH":
            uid_text = str(args[0])
            # S'assure que l'on demande BODY.PEEK (jamais BODY).
            peek = args[1] if len(args) > 1 else ""
            self.log.append(("fetch_spec", uid_text, peek))
            return ("OK", self.messages.get(int(uid_text), []))
        return ("OK", [])

    def logout(self):
        self.log.append(("logout",))

    def shutdown(self):
        self.log.append(("shutdown",))


class IMAPClientTests(unittest.TestCase):
    def _factory(self, imap):
        def factory(apple_id, password):
            # Même contrat que default_imap_factory : login + select readonly.
            imap.login(apple_id, password)
            imap.select("INBOX", readonly=True)
            return imap

        return factory

    def test_readonly_and_peek_only(self):
        uid1 = _make_email(1, "Sujet", "a@b.fr", "Corps du mail.")
        uid2 = _make_email(2, "Autre", "c@d.fr", "Un autre corps.")
        imap = FakeIMAP([1, 2], unseen=[1], messages={1: uid1, 2: uid2})
        client = ICloudIMAPClient(
            "u@icloud.com", "app-pass", imap_factory=self._factory(imap)
        )
        messages = client.recent_messages(datetime(2026, 11, 20, tzinfo=PARIS))

        self.assertEqual([m["subject"] for m in messages], ["Autre", "Sujet"])
        self.assertEqual(messages[1]["unread"], True)
        self.assertEqual(messages[0]["unread"], False)
        self.assertEqual(imap._select_called, ("INBOX", True))
        # Aucune commande d'écriture, et FETCH en BODY.PEEK uniquement.
        verbs = [entry[1] for entry in imap.log if entry[0] == "uid"]
        self.assertNotIn("STORE", verbs)
        self.assertNotIn("EXPUNGE", verbs)
        self.assertNotIn("APPEND", verbs)
        for entry in imap.log:
            if entry[0] == "fetch_spec":
                self.assertIn("PEEK", entry[2])

    def test_max_messages_bounds_fetches(self):
        messages = {u: _make_email(u, f"S{u}", "x@y.fr", "body") for u in range(1, 8)}
        imap = FakeIMAP(list(range(1, 8)), unseen=[], messages=messages)
        client = ICloudIMAPClient(
            "u@icloud.com", "app-pass", max_messages=3, imap_factory=self._factory(imap)
        )
        items = client.recent_messages(datetime(2026, 11, 20, tzinfo=PARIS))
        self.assertEqual(len(items), 3)
        fetched = [e[1] for e in imap.log if e[0] == "fetch_spec"]
        self.assertEqual(sorted(fetched), ["5", "6", "7"])

    def test_login_failure(self):
        def raising_factory(apple_id, password):
            raise imap.IMAPError("Authentification iCloud refusée.")

        client = ICloudIMAPClient(
            "u@icloud.com", "mauvais", imap_factory=raising_factory
        )
        with self.assertRaises(IMAPError):
            client.recent_messages(datetime(2026, 11, 20, tzinfo=PARIS))


# ---------------------------------------------------------------------------
# Collecte (statuts, partiel)
# ---------------------------------------------------------------------------

class _FakeCalendar:
    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error

    def events_overlapping(self, start, end):
        if self.error is not None:
            raise self.error
        return self.events


class _FakeIMAPClient:
    def __init__(self, messages=None, error=None):
        self.messages = messages or []
        self.error = error

    def recent_messages(self, now):
        if self.error is not None:
            raise self.error
        return self.messages


def _config(configured=True):
    if not configured:
        return BriefingConfig(apple_id="", app_password="", timezone="Europe/Paris")
    return BriefingConfig(apple_id="u@icloud.com", app_password="app-pass", timezone="Europe/Paris")


class ConfigTests(unittest.TestCase):
    def test_load_env_with_mail_login(self):
        from briefing.config import load_config

        with patch.dict(
            "os.environ",
            {
                "ICLOUD_APPLE_ID": "user@gmail.com",
                "ICLOUD_MAIL_LOGIN": "user@icloud.com",
                "ICLOUD_APP_PASSWORD": "xxxx-xxxx-xxxx-xxxx",
                "BRIEFING_TIME_ZONE": "America/Toronto",
            },
            clear=False,
        ):
            cfg = load_config()
            self.assertEqual(cfg.apple_id, "user@gmail.com")
            self.assertEqual(cfg.imap_login, "user@icloud.com")
            self.assertEqual(cfg.timezone, "America/Toronto")
            self.assertTrue(cfg.configured)

    def test_imap_login_falls_back_to_apple_id(self):
        cfg = BriefingConfig(apple_id="user@gmail.com", app_password="secret")
        self.assertEqual(cfg.imap_login, "user@gmail.com")


class CollectorTests(unittest.TestCase):
    def _now(self):
        return datetime(2026, 11, 20, 9, 0, tzinfo=PARIS)

    def test_not_configured_sources(self):
        payload = BriefingCollector(_config(configured=False), now=self._now()).collect()
        self.assertEqual(payload["calendar"]["status"], collect.NOCONFIG)
        self.assertEqual(payload["emails"]["status"], collect.NOCONFIG)
        self.assertTrue(payload["partial"])

    def test_ok_reports_empty_sources_without_partial(self):
        collector = BriefingCollector(
            _config(),
            calendar_client=_FakeCalendar(events=[]),
            imap_client=_FakeIMAPClient(messages=[]),
            now=self._now(),
        )
        payload = collector.collect()
        self.assertEqual(payload["calendar"], {"status": collect.OK, "events": []})
        self.assertFalse(payload["partial"])

    def test_calendar_unavailable_partial(self):
        collector = BriefingCollector(
            _config(),
            calendar_client=_FakeCalendar(error=CalDAVError("nope")),
            imap_client=_FakeIMAPClient(
                messages=[{"id": "1", "subject": "S", "body": "b"}]
            ),
            now=self._now(),
        )
        payload = collector.collect()
        self.assertEqual(payload["calendar"]["status"], collect.UNAVAILABLE)
        self.assertEqual(payload["emails"]["status"], collect.OK)
        self.assertTrue(payload["partial"])

    def test_emails_unavailable_partial(self):
        collector = BriefingCollector(
            _config(),
            calendar_client=_FakeCalendar(events=[{"summary": "E"}]),
            imap_client=_FakeIMAPClient(error=IMAPError("nope")),
            now=self._now(),
        )
        payload = collector.collect()
        self.assertEqual(payload["emails"]["status"], collect.UNAVAILABLE)
        self.assertTrue(payload["partial"])


# ---------------------------------------------------------------------------
# Rendu déterministe
# ---------------------------------------------------------------------------

class RenderTests(unittest.TestCase):
    def _payload(self, calendar_status, email_status, *, partial=True):
        return {
            "day": "2026-11-20",
            "timezone": "Europe/Paris",
            "generated_at": "2026-11-20T09:00:00+01:00",
            "calendar": statused(calendar_status),
            "emails": statused(email_status),
            "partial": partial,
        }

    def test_renders_events(self):
        base = {
            "day": "2026-11-20",
            "timezone": "Europe/Paris",
            "generated_at": "2026-11-20T09:00:00+01:00",
            "partial": False,
            "calendar": {
                "status": "ok",
                "events": [
                    {
                        "id": "1",
                        "summary": "Réunion",
                        "all_day": False,
                        "start": "2026-11-20T09:30:00+01:00",
                        "end": "2026-11-20T10:30:00+01:00",
                        "location": "Salle A",
                        "calendar": "Perso",
                    },
                    {
                        "id": "2",
                        "summary": "Congés",
                        "all_day": True,
                        "start": "2026-11-20T00:00:00",
                        "end": "2026-11-21T00:00:00",
                        "location": "",
                        "calendar": "Perso",
                    },
                ],
            },
            "emails": statused("ok"),
        }
        text = brief_render.render_briefing(base)
        self.assertIn("09:30", text)
        self.assertIn("Salle A", text)
        self.assertIn("Toute la journée — Congés", text)
        self.assertIn("vendredi 20 novembre", text)

    def test_no_events_vs_unavailable_vs_not_configured(self):
        empty = self._payload("ok", "ok", partial=False)
        empty_out = brief_render.render_briefing(empty)
        self.assertIn("Aucun rendez-vous", empty_out)

        down = self._payload("unavailable", "ok")
        down_out = brief_render.render_briefing(down)
        self.assertIn("indisponible", down_out)

        noconfig = self._payload("not_configured", "not_configured")
        noconfig_out = brief_render.render_briefing(noconfig)
        self.assertIn("non configuré", noconfig_out)

    def test_partial_note(self):
        text = brief_render.render_briefing(self._payload("unavailable", "ok"))
        self.assertIn("partiel", text.lower())

    def test_emails_unread_marker(self):
        payload = self._payload("ok", "ok", partial=False)
        payload["emails"] = {
            "status": "ok",
            "messages": [
                {
                    "id": "1",
                    "subject": "Note de service",
                    "from": "direction <dir@exemple.fr>",
                    "date": "2026-11-20T08:00:00+01:00",
                    "body": "…",
                    "unread": True,
                }
            ],
        }
        text = brief_render.render_briefing(payload)
        self.assertIn("Note de service", text)
        self.assertIn("[non lu]", text)


def statused(status):
    data = {
        "ok": {"status": "ok", "events": []},
        "unavailable": {"status": "unavailable", "events": []},
        "not_configured": {"status": "not_configured", "events": []},
    }["ok" if status == "ok" else status]
    if "events" not in data and status == "ok":
        data = {"status": "ok", "events": []}
    return data


class DetectTests(unittest.TestCase):
    def test_positive_requests(self):
        for text in (
            "Fais-moi le point sur ma journée",
            "Peux-tu faire le point sur la journée ?",
            "Fais le point du jour",
            "Briefing de la journée",
            "Donne-moi le point de mon agenda",
            "Fais le point sur mon planning svp",
        ):
            self.assertTrue(is_daily_briefing_request(text), text)

    def test_negative_requests(self):
        for text in (
            "Salut",
            "Bonjour",
            "Question unique",
            "Ajoute une tâche à ma liste",
            "",
        ):
            self.assertFalse(is_daily_briefing_request(text), text)


# ---------------------------------------------------------------------------
# Endpoint Django /api/briefing/ + commande chat
# ---------------------------------------------------------------------------

def _stream_body(response):
    return "".join(chunk.decode("utf-8") for chunk in response.streaming_content)


def _ndjson(body):
    return [json.loads(line) for line in body.splitlines() if line.strip()]


class BriefingEndpointTests(TestCase):
    def test_get_returns_structured_data(self):
        payload = {"day": "2026-11-20", "calendar": {"status": "ok", "events": []}}
        with patch("assistant.views.structured_briefing", return_value=payload):
            response = self.client.get("/api/briefing/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["day"], "2026-11-20")

    def test_post_returns_text(self):
        with patch("assistant.views.provide_daily_briefing", return_value="Brief texte."):
            response = self.client.post(
                "/api/briefing/", {}, content_type="application/json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "Brief texte."})

    @override_settings(BRIEFING_API_KEY="cle-secrete")
    def test_api_key_required_when_set(self):
        with patch("assistant.views.structured_briefing", return_value={}):
            denied = self.client.get("/api/briefing/")
            ok_header = self.client.get(
                "/api/briefing/", HTTP_AUTHORIZATION="Bearer cle-secrete"
            )
            ok_x = self.client.get("/api/briefing/", HTTP_X_BRIEFING_KEY="cle-secrete")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(ok_header.status_code, 200)
        self.assertEqual(ok_x.status_code, 200)

    @override_settings(BRIEFING_API_KEY="cle-secrete")
    def test_api_key_wrong_rejected(self):
        with patch("assistant.views.structured_briefing", return_value={}):
            response = self.client.get(
                "/api/briefing/", HTTP_AUTHORIZATION="Bearer autre"
            )
        self.assertEqual(response.status_code, 401)


class ChatBriefingCommandTests(TestCase):
    def test_chat_returns_briefing_without_ollama(self):
        with patch("assistant.views.provide_daily_briefing", return_value="Le point du jour."):
            response = self.client.post(
                "/api/chat/",
                {"message": "Fais-moi le point sur ma journée"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reply"], "Le point du jour.")
        conversation_id = data["conversation_id"]

    def test_chat_stream_emits_briefing_delta(self):
        with patch("assistant.views.provide_daily_briefing", return_value="Brief stream."):
            response = self.client.post(
                "/api/chat/stream/",
                {"message": "Fais-moi le point sur ma journée"},
                content_type="application/json",
            )
            # Le corps NDJSON est consommé dans le bloc patch : le générateur
            # s'exécute à la lecture du streaming.
            body = _stream_body(response)
        self.assertEqual(response.status_code, 200)
        events = _ndjson(body)
        self.assertEqual(events[0]["type"], "start")
        deltas = [e["content"] for e in events if e["type"] == "delta"]
        self.assertEqual(deltas, ["Brief stream."])
        self.assertEqual(events[-1]["type"], "done")

    @patch("assistant.services.requests.post")
    def test_ordinary_message_still_uses_ollama(self, mock_post):
        with patch(
            "assistant.views.provide_daily_briefing",
            side_effect=AssertionError("briefing appelé à tort"),
        ):
            mock_post.return_value = _fake_response(
                json.dumps({"message": {"content": "Réponse classique"}})
            )
            response = self.client.post(
                "/api/chat/",
                {"message": "Question unique"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Réponse classique")


class _FakeHTTPResponse:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)

    def iter_lines(self, decode_unicode=False):
        for line in self.text.splitlines():
            yield line if decode_unicode else line.encode("utf-8")

    def close(self):
        return None


def _fake_response(text):
    return _FakeHTTPResponse(text)


if __name__ == "__main__":
    unittest.main()
