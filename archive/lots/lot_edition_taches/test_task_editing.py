import json

from django.test import TestCase
from django.urls import reverse

from .models import Task


class TaskEditingTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            title="Ancien titre", description="Ancienne description", status=Task.Status.DONE,
        )
        self.url = reverse("task-detail", kwargs={"task_id": self.task.pk})
        self.version = self.task.updated_at.isoformat()

    def patch(self, data):
        return self.client.patch(self.url, data=json.dumps(data), content_type="application/json")

    def delete(self, data):
        return self.client.delete(self.url, data=json.dumps(data), content_type="application/json")

    def test_edit_title_description_preserves_status(self):
        response = self.patch({"title": "Nouveau titre", "description": "Détail", "expected_updated_at": self.version})
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Nouveau titre")
        self.assertEqual(self.task.description, "Détail")
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertEqual(response.json()["id"], self.task.pk)

    def test_empty_title_rejected(self):
        response = self.patch({"title": "   ", "expected_updated_at": self.version})
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Ancien titre")

    def test_long_description_rejected(self):
        response = self.patch({"description": "a" * 2001})
        self.assertEqual(response.status_code, 400)

    def test_stale_edit_does_not_overwrite(self):
        self.assertEqual(self.patch({"title": "Autre onglet", "expected_updated_at": self.version}).status_code, 200)
        response = self.patch({"title": "Modification périmée", "expected_updated_at": self.version})
        self.assertEqual(response.status_code, 409)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Autre onglet")

    def test_stale_delete_does_not_remove(self):
        self.assertEqual(self.patch({"title": "Autre onglet", "expected_updated_at": self.version}).status_code, 200)
        self.assertEqual(self.delete({"expected_updated_at": self.version}).status_code, 409)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_current_version_can_be_deleted(self):
        self.assertEqual(self.delete({"expected_updated_at": self.version}).status_code, 204)
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())

    def test_invalid_or_naive_version_rejected(self):
        for value in ("incorrect", "2026-01-01T12:00:00", 123):
            with self.subTest(value=value):
                response = self.patch({"title": "Ne pas écrire", "expected_updated_at": value})
                self.assertEqual(response.status_code, 400)

    def test_previous_client_without_version_still_works(self):
        response = self.patch({"status": "todo"})
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)
