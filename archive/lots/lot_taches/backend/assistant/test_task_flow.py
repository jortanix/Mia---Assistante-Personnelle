import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import ActionProposal, Conversation, Memory, Task
from .task_rules import InvalidTaskRequest, parse_task_request


class TaskFlowTests(TestCase):
    def propose(self):
        with patch("assistant.views.generate_reply_stream") as generate:
            response = self.client.post(
                reverse("chat-stream"),
                data=json.dumps({"message": "Ajoute une tâche : ranger mon bureau."}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
            generate.assert_not_called()
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        return events[-1]["action_proposal"]

    def resolve(self, proposal, action="confirm"):
        return self.client.post(reverse(
            "action-proposal-" + action,
            kwargs={"proposal_id": proposal["id"]},
        ))

    def create_task(self):
        proposal = self.propose()
        response = self.resolve(proposal)
        self.assertEqual(response.status_code, 200)
        return proposal, response.json()["task"]

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

    def test_proposal_does_not_create_task_or_memory(self):
        proposal = self.propose()
        self.assertEqual(proposal["status"], "pending")
        self.assertIsNone(proposal["task"])
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(Memory.objects.count(), 0)

    def test_confirmation_creates_once(self):
        proposal = self.propose()
        first = self.resolve(proposal)
        second = self.resolve(proposal)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["task"]["id"], second.json()["task"]["id"])
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(Task.objects.get().status, Task.Status.TODO)

    def test_cancellation_blocks_confirmation(self):
        proposal = self.propose()
        self.assertEqual(self.resolve(proposal, "cancel").status_code, 200)
        self.assertEqual(self.resolve(proposal).status_code, 409)
        self.assertEqual(Task.objects.count(), 0)

    def test_list_excludes_pending_proposals(self):
        self.propose()
        response = self.client.get(reverse("task-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_mark_done_then_todo(self):
        proposal, task = self.create_task()
        url = reverse("task-detail", kwargs={"task_id": task["id"]})
        for new_status in ("done", "todo"):
            response = self.client.patch(url, data=json.dumps({"status": new_status}), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], new_status)
            self.assertEqual(Task.objects.get().status, new_status)

    def test_delete_unlinks_and_does_not_recreate_on_confirm(self):
        proposal, task = self.create_task()
        response = self.client.delete(reverse("task-detail", kwargs={"task_id": task["id"]}))
        self.assertEqual(response.status_code, 204)
        saved = ActionProposal.objects.get(pk=proposal["id"])
        self.assertIsNone(saved.task_id)
        self.assertEqual(saved.status, ActionProposal.Status.CONFIRMED)
        self.assertEqual(self.resolve(proposal).status_code, 200)
        self.assertEqual(Task.objects.count(), 0)

    def test_reopen_preserves_task_proposal(self):
        proposal, task = self.create_task()
        conversation = Conversation.objects.get()
        response = self.client.get(reverse("conversation-detail", kwargs={"conversation_id": conversation.pk}))
        self.assertEqual(response.status_code, 200)
        result = response.json()["action_proposals"][0]
        self.assertEqual(result["id"], proposal["id"])
        self.assertEqual(result["task"]["id"], task["id"])

    def test_invalid_status_rejected(self):
        proposal, task = self.create_task()
        response = self.client.patch(
            reverse("task-detail", kwargs={"task_id": task["id"]}),
            data=json.dumps({"status": "unknown"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Task.objects.get().status, Task.Status.TODO)

    def test_direct_creation_endpoint_not_allowed(self):
        response = self.client.post(reverse("task-list"), data={"title": "Sans confirmation"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Task.objects.count(), 0)

    @patch("assistant.views.generate_reply_stream")
    def test_ordinary_chat_is_unchanged(self, generate):
        generate.return_value = iter([("delta", "Bonjour"), ("done", "Bonjour")])
        response = self.client.post(reverse("chat-stream"), data=json.dumps({"message": "Bonjour"}), content_type="application/json")
        events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
        self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)

    def test_non_streaming_chat_proposes_task_too(self):
        response = self.client.post(reverse("chat"), data={"message": "Ajoute une tâche : ranger"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action_proposal"]["action"], "create_task")
        self.assertEqual(Task.objects.count(), 0)
