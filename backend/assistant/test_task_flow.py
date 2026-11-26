import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import ActionProposal, Conversation, Memory, Task
from .task_rules import InvalidTaskRequest, parse_task_request


class TaskFlowTests(TestCase):
    def stream_events(self, message="Ajoute une tâche : ranger mon bureau."):
        with patch("assistant.views.generate_reply_stream") as generate:
            response = self.client.post(
                reverse("chat-stream"),
                data=json.dumps({"message": message}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
            generate.assert_not_called()
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        return events

    def test_explicit_commands(self):
        for text in (
            "Ajoute une tâche : ranger mon bureau.",
            "Crée une tâche : ranger mon bureau",
            "Mia, ajoute une tâche : ranger mon bureau",
            "Peux-tu ajouter une tâche : ranger mon bureau",
            "Ajoute à mes tâches : ranger mon bureau",
        ):
            with self.subTest(text=text):
                result = parse_task_request(text)
                self.assertEqual(result["action"], "create_task")
                self.assertEqual(result["data"]["title"], "ranger mon bureau")

    def test_no_inference_from_mentions_negation_or_quotes(self):
        for text in (
            "Je dois ranger mon bureau", "N'ajoute pas une tâche : ranger",
            'Il dit : "Ajoute une tâche : ranger"',
            "Faut-il ajouter une tâche : ranger ?",
            "Je préfère des réponses courtes.",
        ):
            self.assertEqual(parse_task_request(text), {"action": "none"})

    def test_reject_empty_and_long_titles(self):
        for text in ("Ajoute une tâche", "Ajoute une tâche :", "Ajoute une tâche : " + "a" * 201):
            with self.assertRaises(InvalidTaskRequest):
                parse_task_request(text)

    def test_stream_creates_task_directly(self):
        events = self.stream_events()
        task = events[-1]["task"]
        self.assertEqual(task["title"], "ranger mon bureau")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(Task.objects.get().title, "ranger mon bureau")
        # Plus aucune proposition à confirmer.
        self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)
        self.assertEqual(Memory.objects.count(), 0)

    def test_non_streaming_chat_creates_task_too(self):
        response = self.client.post(reverse("chat"), data={"message": "Ajoute une tâche : ranger"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["task"]["title"], "ranger")
        self.assertIn("ranger", body["reply"])
        self.assertEqual(Task.objects.count(), 1)

    def test_list_shows_created_task(self):
        self.stream_events()
        response = self.client.get(reverse("task-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["title"], "ranger mon bureau")

    def test_mark_done_then_todo(self):
        self.stream_events()
        task = Task.objects.get()
        url = reverse("task-detail", kwargs={"task_id": task.pk})
        for new_status in ("done", "todo"):
            response = self.client.patch(url, data=json.dumps({"status": new_status}), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], new_status)
            task.refresh_from_db()
            self.assertEqual(task.status, new_status)

    def test_ordinary_chat_is_unchanged(self):
        with patch("assistant.views.generate_reply_stream") as generate:
            generate.return_value = iter([("delta", "Bonjour"), ("done", "Bonjour")])
            response = self.client.post(reverse("chat-stream"), data=json.dumps({"message": "Bonjour"}), content_type="application/json")
            events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
            self.assertNotIn("task", events[-1])
            self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(ActionProposal.objects.count(), 0)


class TaskApiTests(TestCase):
    """Les endpoints de gestion des tâches restent inchangés."""

    def test_direct_creation_endpoint_not_allowed(self):
        response = self.client.post(reverse("task-list"), data={"title": "Sans confirmation"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Task.objects.count(), 0)

    def test_invalid_status_rejected(self):
        task = Task.objects.create(title="Existant")
        response = self.client.patch(
            reverse("task-detail", kwargs={"task_id": task.pk}),
            data=json.dumps({"status": "unknown"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.TODO)
