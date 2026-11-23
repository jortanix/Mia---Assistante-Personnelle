from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import ActionProposal, Conversation, Memory, Message
from .services import build_messages


class MemoryManagementTests(TestCase):
    def setUp(self):
        self.memory = Memory.objects.create(content="Je préfère des réponses courtes.")
        conversation = Conversation.objects.create()
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.ASSISTANT,
            content="Veux-tu retenir cette préférence ?",
        )
        self.proposal = ActionProposal.objects.create(
            conversation=conversation, assistant_message=message,
            action=ActionProposal.Action.SAVE_MEMORY,
            data={"content": self.memory.content},
            status=ActionProposal.Status.CONFIRMED, memory=self.memory,
        )

    def test_list_returns_saved_preferences(self):
        response = self.client.get(reverse("memory-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["content"], self.memory.content)

    def test_cannot_create_memory_through_list(self):
        response = self.client.post(reverse("memory-list"), {"content": "Autre"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Memory.objects.count(), 1)

    def test_delete_unlinks_proposal_but_preserves_history(self):
        response = self.client.delete(reverse("memory-detail", kwargs={"memory_id": self.memory.pk}))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Memory.objects.count(), 0)
        self.proposal.refresh_from_db()
        self.assertIsNone(self.proposal.memory_id)
        self.assertEqual(self.proposal.status, ActionProposal.Status.CONFIRMED)
        self.assertTrue(Message.objects.filter(pk=self.proposal.assistant_message_id).exists())

    def test_disabled_by_default_and_no_database_query(self):
        with self.assertNumQueries(0):
            messages = build_messages("Bonjour")
        self.assertEqual(len(messages), 2)

    def test_enabled_uses_saved_not_pending(self):
        self.proposal.status = ActionProposal.Status.PENDING
        self.proposal.memory = None
        self.proposal.data = {"content": "PREFERENCE_NON_CONFIRMEE"}
        self.proposal.save()
        messages = build_messages("Bonjour", use_memory=True)
        self.assertIn(self.memory.content, messages[1]["content"])
        self.assertNotIn("PREFERENCE_NON_CONFIRMEE", str(messages))

    def test_deleted_preference_not_in_new_messages(self):
        self.memory.delete()
        self.assertEqual(len(build_messages("Bonjour", use_memory=True)), 2)

    def test_only_ten_most_recent(self):
        for index in range(12):
            Memory.objects.create(content=f"Preference {index}")
        messages = build_messages("Bonjour", use_memory=True)
        self.assertNotIn(self.memory.content, messages[1]["content"])
        self.assertIn("Preference 11", messages[1]["content"])

    @patch("assistant.views.generate_reply_stream")
    def test_stream_passes_explicit_memory_choice(self, generate):
        generate.return_value = iter([("delta", "Bonjour"), ("done", "Bonjour")])
        response = self.client.post(
            reverse("chat-stream"),
            data={"message": "Bonjour", "use_memory": True},
            content_type="application/json",
        )
        list(response.streaming_content)
        self.assertTrue(generate.call_args.kwargs["use_memory"])
