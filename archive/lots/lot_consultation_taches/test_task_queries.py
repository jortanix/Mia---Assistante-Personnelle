import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ActionProposal, Conversation, Memory, Task
from .task_queries import build_task_answer, detect_task_query


class TaskQueryTests(TestCase):
    def test_supported_phrases(self):
        cases = {
            "Quelles sont mes tâches ?": "todo",
            "Mia, que me reste-t-il à faire ?": "todo",
            "Liste toutes mes tâches.": "all",
            "Quelles sont mes tâches terminées ?": "done",
            "Combien de tâches me reste-t-il ?": "count",
            "Aide-moi à choisir une tâche.": "choose",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(detect_task_query(message), kind)

    def test_other_messages_are_not_intercepted(self):
        for message in (
            "Supprime toutes mes tâches", "Ne liste pas mes tâches",
            'Elle dit : "Quelles sont mes tâches ?"',
            "Mon bureau est en désordre, aide-moi à commencer",
            "Je préfère des réponses courtes.",
            "Ajoute une tâche : ranger",
        ):
            self.assertIsNone(detect_task_query(message))
            self.assertIsNone(build_task_answer(message))

    def test_empty_list(self):
        self.assertIn("aucune tâche à faire", build_task_answer("Liste mes tâches"))
        self.assertIn("aucune tâche enregistrée", build_task_answer("Liste toutes mes tâches"))

    def test_todo_uses_real_data_and_limits_to_three(self):
        for index in range(5):
            Task.objects.create(title=f"À faire {index}")
        Task.objects.create(title="DEJA_TERMINEE", status=Task.Status.DONE)
        answer = build_task_answer("Liste mes tâches")
        self.assertIn("5 tâches à faire", answer)
        self.assertIn("À faire 0", answer)
        self.assertNotIn("À faire 4", answer)
        self.assertNotIn("DEJA_TERMINEE", answer)
        self.assertIn("Mes tâches", answer)

    def test_all_limits_to_ten_and_shows_status(self):
        for index in range(12):
            Task.objects.create(title=f"Élément {index}", status=Task.Status.DONE if index == 0 else Task.Status.TODO)
        answer = build_task_answer("Liste toutes mes tâches")
        self.assertIn("12 tâches enregistrées", answer)
        self.assertIn("Élément 0 — Terminée", answer)
        self.assertNotIn("Élément 11", answer)

    def test_count_and_done_filter(self):
        Task.objects.create(title="UNIQUE_A_FAIRE")
        Task.objects.create(title="TERMINEE", status=Task.Status.DONE)
        self.assertIn("1 tâche à faire", build_task_answer("Combien de tâches me reste-t-il ?"))
        answer = build_task_answer("Liste mes tâches terminées")
        self.assertIn("TERMINEE", answer)
        self.assertNotIn("UNIQUE_A_FAIRE", answer)

    def test_choose_returns_oldest_todo_only(self):
        Task.objects.create(title="TERMINEE", status=Task.Status.DONE)
        old = Task.objects.create(title="ANCIENNE")
        Task.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        Task.objects.create(title="NOUVELLE")
        answer = build_task_answer("Aide-moi à choisir une tâche")
        self.assertIn("ANCIENNE", answer)
        self.assertNotIn("NOUVELLE", answer)
        self.assertNotIn("TERMINEE", answer)

    @patch("assistant.views.generate_reply_stream")
    def test_stream_saves_answer_without_model_or_task_changes(self, generate):
        Task.objects.create(title="Lire le document")
        response = self.client.post(reverse("chat-stream"),
            data=json.dumps({"message": "Quelles sont mes tâches ?"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        self.assertIn("Lire le document", events[1]["content"])
        generate.assert_not_called()
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(Task.objects.get().status, Task.Status.TODO)
        self.assertEqual(ActionProposal.objects.count(), 0)
        self.assertEqual(Memory.objects.count(), 0)
        self.assertEqual(Conversation.objects.get().messages.count(), 2)

    @patch("assistant.views.generate_reply")
    def test_non_streaming_route(self, generate):
        Task.objects.create(title="Faire une pause")
        response = self.client.post(reverse("chat"), data={"message": "Liste mes tâches"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Faire une pause", response.json()["reply"])
        generate.assert_not_called()

    def test_read_reflects_status_changes_and_deletion(self):
        task = Task.objects.create(title="À traiter")
        self.assertIn("À traiter", build_task_answer("Liste mes tâches"))
        task.status = Task.Status.DONE
        task.save()
        self.assertNotIn("À traiter", build_task_answer("Liste mes tâches"))
        self.assertIn("À traiter", build_task_answer("Liste mes tâches terminées"))
        task.delete()
        self.assertIn("aucune", build_task_answer("Liste toutes mes tâches"))
