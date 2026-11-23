import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .memory_rules import detect_memory_preference
from .models import ActionProposal, Conversation, Memory


class MemoryProposalTests(TestCase):
    def stream(self, message, conversation_id=None):
        body = {"message": message}
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        response = self.client.post(
            reverse("chat-stream"), data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]

    def test_supported_preference_preserves_exact_text(self):
        content = "Je préfère des réponses courtes."
        self.assertEqual(detect_memory_preference(content), content)

    def test_rejects_negation_quotes_sensitive_and_extra_text(self):
        for text in (
            "Ne retiens pas que je préfère des réponses courtes.",
            'Elle dit : "Je préfère des réponses courtes."',
            "Je préfère le traitement médical X.",
            "Je préfère des réponses courtes. Mon mot de passe est secret.",
            "Est-ce que je préfère des réponses courtes ?",
            "Je préfère des réponses courtes parce que je suis malade.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_memory_preference(text))

    @patch("assistant.views.generate_reply_stream")
    def test_proposal_full_lifecycle_and_reopen(self, generate):
        events = self.stream("Je préfère des réponses courtes.")
        generate.assert_not_called()
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        proposal = events[-1]["action_proposal"]
        self.assertEqual(proposal["status"], "pending")
        self.assertIsNone(proposal["memory"])
        self.assertEqual(Memory.objects.count(), 0)
        detail_url = reverse("conversation-detail", kwargs={
            "conversation_id": events[0]["conversation_id"],
        })
        detail = self.client.get(detail_url).json()
        self.assertEqual(detail["action_proposals"][0]["id"], proposal["id"])
        response = self.client.post(reverse("action-proposal-confirm", kwargs={
            "proposal_id": proposal["id"],
        }))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Memory.objects.count(), 1)
        self.assertEqual(Memory.objects.get().content, "Je préfère des réponses courtes.")
        detail = self.client.get(detail_url).json()
        self.assertEqual(detail["action_proposals"][0]["status"], "confirmed")

    @patch("assistant.views.generate_reply_stream")
    def test_normal_chat_still_streams_without_proposal(self, generate):
        generate.return_value = iter([("delta", "Bonjour."), ("done", "Bonjour.")])
        events = self.stream("Bonjour Mia")
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)
        self.assertEqual(Conversation.objects.get().messages.count(), 2)
