from django.test import TestCase
from django.urls import reverse

from .models import BrainrotEvent


class BrainrotApiTests(TestCase):
    def test_list_is_empty_by_default(self):
        response = self.client.get(reverse("brainrot-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_create_lapse(self):
        response = self.client.post(
            reverse("brainrot-list"),
            {"app": "TikTok", "lapsed": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["app"], "TikTok")
        self.assertTrue(data["lapsed"])
        self.assertIn("created_at", data)
        self.assertEqual(BrainrotEvent.objects.count(), 1)

    def test_create_resistance_without_app(self):
        response = self.client.post(
            reverse("brainrot-list"),
            {"lapsed": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["app"], "")
        self.assertFalse(response.json()["lapsed"])

    def test_create_defaults_to_lapsed(self):
        response = self.client.post(
            reverse("brainrot-list"),
            {"app": "Instagram"},
            content_type="application/json",
        )
        self.assertTrue(response.json()["lapsed"])

    def test_list_orders_most_recent_first(self):
        BrainrotEvent.objects.create(app="TikTok", lapsed=True)
        BrainrotEvent.objects.create(app="Threads", lapsed=False)
        response = self.client.get(reverse("brainrot-list"))
        apps = [item["app"] for item in response.json()]
        self.assertEqual(apps, ["Threads", "TikTok"])

    def test_delete_event(self):
        event = BrainrotEvent.objects.create(app="TikTok", lapsed=True)
        response = self.client.delete(reverse("brainrot-detail", kwargs={"event_id": event.pk}))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(BrainrotEvent.objects.count(), 0)

    def test_delete_missing_event_returns_404(self):
        response = self.client.delete(reverse("brainrot-detail", kwargs={"event_id": 9999}))
        self.assertEqual(response.status_code, 404)
