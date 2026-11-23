"""Briefing iCloud — agenda + mails en lecture seule pour MIA.

Package séparé (``backend/briefing/``), indépendant d'OpenJarvis : tout est
builtin (``imaplib``, ``xml.etree``, ``requests``) et la configuration se
lit dans l'environnement. Aucune écriture n'est jamais émise côté iCloud.
"""

from .collect import (
    NOCONFIG,
    OK,
    UNAVAILABLE,
    BriefingCollector,
    resolve_timezone,
)
from .config import BriefingConfig, load_config
from .detect import is_daily_briefing_request
from .render import render_briefing
from .service import provide_daily_briefing, structured_briefing

__version__ = "0.1.0"

__all__ = [
    "BriefingCollector",
    "BriefingConfig",
    "NOCONFIG",
    "OK",
    "UNAVAILABLE",
    "is_daily_briefing_request",
    "load_config",
    "provide_daily_briefing",
    "render_briefing",
    "resolve_timezone",
    "structured_briefing",
]
