"""Adaptateur IMAP iCloud minimal — lecture seule.

La classe :class:`~briefing.imap.ICloudIMAPClient` ouvre une session IMAPS
sur ``imap.mail.me.com``, sélectionne la boîte de réception ``INBOX`` en
lecture seule et remonte quelques mails récents.

Garanties :
- ``select("INBOX", readonly=True)`` et ``FETCH BODY.PEEK[]`` : ouvrir ou
  résumer un mail ne le marque jamais comme lu ;
- aucune opération d'écriture IMAP (``STORE``, ``APPEND``, ``EXPUNGE``,
  ``COPY``, ``MOVE``…) n'est jamais émise ;
- seule une fenêtre temporelle limitée est lue (``SINCE`` puis
  ``max_messages``), l'ensemble de la boîte n'est pas indexé ;
- les identifiants ne sont jamais journalisés ni inclus dans les erreurs.

La session (ouverture TLS, authentification, sélection) est créée par une
fabrique injectable pour permettre les tests sans boîte réelle.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import ssl
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Set

_DEFAULT_HOST = "imap.mail.me.com"
_DEFAULT_PORT = 993
_IMAP_TIMEOUT = 30

IMAP4 = imaplib.IMAP4


class IMAPError(Exception):
    """Échec d'une lecture IMAP (réseau, authentification, réponse invalide)."""


def _decode_header_value(raw: Any) -> str:
    """Décode un en-tête e-mail (déclarations RFC 2047, octets bruts)."""
    if not raw:
        return ""
    out: List[str] = []
    for part, enc in decode_header(raw if isinstance(raw, str) else str(raw)):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _extract_text_body(msg: email_lib.message.Message) -> str:
    """Extrait le corps texte d'un message (repli sur text/html)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace")
    return ""


def _parse_mail_date(msg: email_lib.message.Message) -> Optional[datetime]:
    date_str = msg.get("Date", "")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _default_imap_factory(apple_id: str, app_password: str) -> IMAP4:
    """Connexion IMAPS iCloud authentifiée, INBOX sélectionnée read-only."""
    context = ssl.create_default_context()
    try:
        imap = imaplib.IMAP4_SSL(
            _DEFAULT_HOST, _DEFAULT_PORT, ssl_context=context, timeout=_IMAP_TIMEOUT
        )
    except (OSError, imaplib.IMAP4.error) as exc:
        raise IMAPError("Connexion IMAP impossible.") from exc
    try:
        status, _ = imap.login(apple_id, app_password)
        if status != "OK":
            raise imaplib.IMAP4.error("connexion refusée")
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error("sélection INBOX refusée")
    except (imaplib.IMAP4.error, OSError) as exc:
        try:
            imap.logout()
        except Exception:
            try:
                imap.shutdown()
            except Exception:
                pass
        raise IMAPError("Authentification iCloud refusée.") from exc
    return imap


class ICloudIMAPClient:
    """Client IMAP iCloud en lecture seule pour le briefing.

    Paramètres
    ----------
    apple_id:
        Adresse du compte iCloud (ex. ``nom@icloud.com``).
    app_password:
        Mot de passe applicatif iCloud.
    since_days:
        Fenêtre temporelle (jours) pour le filtre ``SINCE``.
    max_messages:
        Nombre maximal de mails remontés (les plus récents d'abord).
    body_limit:
        Taille maximale du corps texte conservé par message.
    imap_factory:
        Fabrique de session injectable ``(apple_id, password) -> IMAP4``.
    """

    def __init__(
        self,
        apple_id: str,
        app_password: str,
        *,
        since_days: int = 2,
        max_messages: int = 6,
        body_limit: int = 1200,
        imap_factory: Callable[[str, str], IMAP4] = _default_imap_factory,
    ) -> None:
        if not apple_id or not app_password:
            raise IMAPError("Identifiants IMAP manquants.")
        self._apple_id = apple_id
        self._password = app_password
        self._since_days = max(1, since_days)
        self._max_messages = max(1, max_messages)
        self._body_limit = max(200, body_limit)
        self._imap_factory = imap_factory

    # --- lecture ----------------------------------------------------------

    def recent_messages(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Mails récents de la boîte réception (lecture seule, bornée).

        La connexion est ouverte puis fermée à chaque appel ; rien n'est
        conservé entre deux appels.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        since = (now - timedelta(days=self._since_days)).date()

        imap = None
        try:
            imap = self._imap_factory(self._apple_id, self._password)
        except IMAPError:
            raise
        except Exception as exc:
            raise IMAPError("Ouverture de session IMAP impossible.") from exc
        try:
            uids = self._search_since(imap, since)
            unseen = self._search_unseen(imap)
            messages: List[Dict[str, Any]] = []
            # SEARCH renvoie les UID dans l'ordre croissant : on lit les plus
            # récents d'abord.
            for uid in reversed(uids[-self._max_messages :]):
                message = self._fetch_one(imap, uid)
                if message is not None:
                    message["unread"] = uid in unseen
                    messages.append(message)
            return messages
        finally:
            self._close(imap)

    # --- commandes IMAP (lecture seule) -----------------------------------

    def _search_since(self, imap: IMAP4, since) -> List[int]:
        """UID des messages reçus depuis ``since`` (ordre croissant)."""
        try:
            status, data = imap.uid(
                "SEARCH", None, "SINCE", since.strftime("%d-%b-%Y")
            )
        except (imaplib.IMAP4.error, OSError, ValueError) as exc:
            raise IMAPError("Recherche IMAP impossible.") from exc
        if status != "OK":
            raise IMAPError("Recherche IMAP refusée par le serveur.")
        raw = data[0] if data and data[0] else b""
        return [int(part) for part in raw.split()]

    def _search_unseen(self, imap: IMAP4) -> Set[int]:
        """UID des messages non lus (drapeau \\Seen absent)."""
        try:
            status, data = imap.uid("SEARCH", None, "UNSEEN")
        except (imaplib.IMAP4.error, OSError) as exc:
            raise IMAPError("Recherche IMAP impossible.") from exc
        if status != "OK":
            return set()
        raw = data[0] if data and data[0] else b""
        return {int(part) for part in raw.split()}

    def _fetch_one(self, imap: IMAP4, uid: int) -> Optional[Dict[str, Any]]:
        """Récupère un message via ``BODY.PEEK[]`` (jamais marqué lu)."""
        try:
            status, data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
        except (imaplib.IMAP4.error, OSError) as exc:
            raise IMAPError("Lecture IMAP impossible.") from exc
        if status != "OK":
            return None
        record = next(
            (
                item
                for item in data or []
                if isinstance(item, tuple)
                and len(item) > 1
                and isinstance(item[1], bytes)
            ),
            None,
        )
        if record is None:
            return None
        msg = email_lib.message_from_bytes(record[1])
        received = _parse_mail_date(msg)
        body = _extract_text_body(msg)
        return {
            "id": str(uid),
            "subject": _decode_header_value(msg.get("Subject", "")),
            "from": _decode_header_value(msg.get("From", "")),
            "date": received.isoformat() if received else "",
            "body": body[: self._body_limit],
        }

    @staticmethod
    def _close(imap: Optional[IMAP4]) -> None:
        if imap is None:
            return
        try:
            imap.logout()
        except Exception:
            try:
                imap.shutdown()
            except Exception:
                pass


__all__ = ["IMAPError", "ICloudIMAPClient"]
