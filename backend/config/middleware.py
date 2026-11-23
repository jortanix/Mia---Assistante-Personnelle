"""Garde d'accès mobile pour l'API MIA.

Contrôle par jeton (``MIA_API_KEY`` lue à chaque requête depuis
l'environnement, comme le briefing) :

- tant qu'aucune clé n'est configurée, l'API reste ouverte (usage local) ;
- dès qu'une clé existe, toute requête **non** d'origine locale (par exemple
  l'iPhone via Tailscale ou le Wi-Fi) doit fournir ``Authorization: Bearer
  <clé>`` ou ``X-Mia-Api-Key: <clé>`` ;
- les requêtes d'origine locale (127.0.0.1 / ::1) et le chemin ``/api/briefing/``
  (qui a sa propre clé ``BRIEFING_API_KEY``) ne sont pas concernés.

Le secret n'est jamais journalisé ; la comparaison se fait en temps constant.
"""

from __future__ import annotations

import os
import secrets

from django.http import JsonResponse


def _is_loopback(request) -> bool:
    addr = request.META.get("REMOTE_ADDR", "")
    return addr in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def _provided_key(request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Mia-Api-Key", "").strip()


class MiaApiKeyMiddleware:
    """Exige une clé API pour tout client distant, si MIA_API_KEY est définie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        # Les endpoints du briefing ont leur propre authentification.
        is_api = path.startswith("/api/") and not path.startswith("/api/briefing/")
        if is_api:
            expected = os.environ.get("MIA_API_KEY", "").strip()
            if expected and not _is_loopback(request):
                provided = _provided_key(request)
                if not provided or not secrets.compare_digest(provided, expected):
                    return JsonResponse(
                        {"error": "Accès MIA refusé."},
                        status=401,
                    )
        return self.get_response(request)
