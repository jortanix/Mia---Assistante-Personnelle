"""Tests du socle mobile : garde d'accès par clé API et endpoints rappels."""

import os
import unittest

from django.test import TestCase, override_settings
from unittest.mock import patch

from .models import Reminder


class MiaApiKeyMiddlewareTests(TestCase):
    """La clé MIA_API_KEY protège tout /api/* pour les clients distants."""

    def _remote_client(self, remote_addr="100.100.0.5"):
        return self.client_class(REMOTE_ADDR=remote_addr)

    @patch.dict(os.environ, {}, clear=True)
    @override_settings(MIA_API_KEY="")
    def test_open_when_no_key_configured(self):
        client = self._remote_client()
        response = client.get("/api/tasks/")
        self.assertEqual(response.status_code, 200)

    @patch.dict(os.environ, {"MIA_API_KEY": "mia-secret"}, clear=True)
    def test_remote_requires_key(self):
        client = self._remote_client()
        # Sans jeton : refusé.
        self.assertEqual(client.get("/api/tasks/").status_code, 401)
        # Mauvais jeton : refusé.
        self.assertEqual(
            client.get("/api/tasks/", HTTP_AUTHORIZATION="Bearer mauvais").status_code,
            401,
        )
        # Jeton correct (Authorization: Bearer).
        response = client.get("/api/tasks/", HTTP_AUTHORIZATION="Bearer mia-secret")
        self.assertEqual(response.status_code, 200)
        # Jeton correct (X-Mia-Api-Key).
        response = client.get("/api/tasks/", HTTP_X_MIA_API_KEY="mia-secret")
        self.assertEqual(response.status_code, 200)

    @patch.dict(os.environ, {"MIA_API_KEY": "mia-secret"}, clear=True)
    def test_loopback_exempt(self):
        client = self.client  # 127.0.0.1 par défaut
        response = client.get("/api/tasks/")
        self.assertEqual(response.status_code, 200)

    @patch.dict(
        os.environ,
        {"MIA_API_KEY": "mia-secret", "BRIEFING_API_KEY": ""},
        clear=True,
    )
    def test_briefing_route_not_blocked_by_mia_key(self):
        """Le briefing garde sa clé dédiée : le middleware MIA le laisse passer."""
        client = self._remote_client()
        response = client.get("/api/briefing/")
        # Ni 401 du middleware, ni bloqué : la vue répond (200 avec statuts).
        self.assertEqual(response.status_code, 200)


class ReminderApiTests(TestCase):
    def test_crud_flow(self):
        # Liste vide.
        response = self.client.get("/api/reminders/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

        # Création.
        response = self.client.post(
            "/api/reminders/",
            {"title": "Service du briefing", "due_at": "2026-11-24T08:00:00+01:00"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Service du briefing")
        self.assertFalse(data["done"])
        self.assertEqual(data["repeat"], "none")
        reminder_id = data["id"]

        # Liste après création.
        response = self.client.get("/api/reminders/")
        self.assertEqual(len(response.json()), 1)

        # Marquage comme fait.
        response = self.client.patch(
            f"/api/reminders/{reminder_id}/",
            {"done": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["done"])

        # Suppression.
        response = self.client.delete(f"/api/reminders/{reminder_id}/")
        self.assertEqual(response.status_code, 204)
        response = self.client.get("/api/reminders/")
        self.assertEqual(response.json(), [])

    def test_create_unknown_404(self):
        response = self.client.patch("/api/reminders/999/", {"done": True})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
