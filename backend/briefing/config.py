"""Réglages du briefing iCloud — lus uniquement depuis l'environnement.

Aucun secret n'est jamais codé en dur ici : ``apple_id`` et ``app_password``
proviennent de l'environnement (variables ``ICLOUD_APPLE_ID`` et
``ICLOUD_APP_PASSWORD``) et ne sont pas journalisés.

Deux identifiants de connexion peuvent différer :
- ``apple_id`` — l'identifiant Apple utilisé par CalDAV
  (``ICLOUD_APPLE_ID``, souvent une adresse tierce, ex. ``@gmail.com``) ;
- ``mail_login`` — l'adresse iCloud Mail utilisée par IMAP
  (``ICLOUD_MAIL_LOGIN``, ex. ``prenom_nom@icloud.com``). Sans valeur,
  IMAP reprend ``apple_id``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class BriefingConfig:
    """Réglages d'exécution du briefing (configuration, pas de secrets perdus)."""

    apple_id: str = ""
    mail_login: str = ""
    app_password: str = ""
    timezone: str = "Europe/Paris"
    max_emails: int = 6
    since_days: int = 2
    use_llm: bool = False
    api_key: str = ""
    calendar_limit: int = 200

    @property
    def configured(self) -> bool:
        return bool(self.apple_id and self.app_password)

    @property
    def imap_login(self) -> str:
        """Identifiant IMAP : adresse iCloud Mail, sinon l'Apple ID."""
        return self.mail_login or self.apple_id


def load_config() -> BriefingConfig:
    """Construit la configuration depuis les variables d'environnement."""
    return BriefingConfig(
        apple_id=os.environ.get("ICLOUD_APPLE_ID", "").strip(),
        mail_login=os.environ.get("ICLOUD_MAIL_LOGIN", "").strip(),
        app_password=os.environ.get("ICLOUD_APP_PASSWORD", "").strip(),
        timezone=os.environ.get("BRIEFING_TIME_ZONE", "Europe/Paris").strip()
        or "Europe/Paris",
        max_emails=_env_int("BRIEFING_MAX_EMAILS", 6),
        since_days=_env_int("BRIEFING_SINCE_DAYS", 2),
        use_llm=_env_bool("BRIEFING_USE_LLM"),
        api_key=os.environ.get("BRIEFING_API_KEY", "").strip(),
        calendar_limit=_env_int("BRIEFING_CALENDAR_LIMIT", 200),
    )


def redacted_credentials(apple_id: str, password: str) -> str:
    """Résumé sûr pour journaliser sans révéler de secret."""
    if not apple_id:
        return "(absent)"
    local, _, domain = apple_id.partition("@")
    left = local[:3] if local else ""
    return f"{left}***@{domain if domain else '…'} (mot de passe fourni : {'oui' if password else 'non'})"


__all__ = ["BriefingConfig", "load_config", "redacted_credentials"]
