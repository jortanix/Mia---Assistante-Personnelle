"""Service briefing — la commande Mia et l'API structurée.

Le flux : config → clients (CalDAV + IMAP) → collecte → rendu déterministe →
reformulation LLM facultative (le texte déterministe reste la référence).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .caldav import ICloudCalDAVClient
from .collect import BriefingCollector
from .config import BriefingConfig, load_config
from .imap import ICloudIMAPClient
from .llm import refine_with_llm
from .render import render_briefing


def _build_collector(
    config: BriefingConfig, now: Optional[datetime]
) -> BriefingCollector:
    if not config.configured:
        return BriefingCollector(config, now=now)
    calendar_client = ICloudCalDAVClient(
        config.apple_id,
        config.app_password,
        timezone=config.timezone,
        limit=config.calendar_limit,
    )
    imap_client = ICloudIMAPClient(
        config.imap_login,
        config.app_password,
        since_days=config.since_days,
        max_messages=config.max_emails,
    )
    return BriefingCollector(
        config,
        calendar_client=calendar_client,
        imap_client=imap_client,
        now=now,
    )


def structured_briefing(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Données structurées du briefing (agenda + mails) pour l'API GET."""
    config = load_config()
    return _build_collector(config, now).collect()


def provide_daily_briefing(
    now: Optional[datetime] = None, *, request_llm: bool = True
) -> str:
    """Texte du point sur la journée pour la commande Mia.

    ``request_llm`` ne force rien : la reformulation n'a lieu que si elle est
    aussi activée par ``BRIEFING_USE_LLM`` dans l'environnement.
    """
    config = load_config()
    collector = _build_collector(config, now)
    payload = collector.collect()
    text = render_briefing(payload)
    if request_llm and config.use_llm:
        refined = refine_with_llm(text)
        if refined:
            text = refined
    return text


__all__ = ["provide_daily_briefing", "structured_briefing"]
