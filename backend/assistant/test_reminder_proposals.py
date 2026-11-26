import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import ActionProposal, Conversation, Reminder
from .reminder_rules import InvalidReminderRequest, parse_reminder_request


class ReminderRulesTests(TestCase):
    def test_explicit_commands(self):
        for text, expected_title in (
            ("Rappelle-moi de boire de l'eau dans 1 heure", "boire de l'eau"),
            ("rappelle-moi de prendre un médicament à 18h", "prendre un médicament"),
            ("Peux-tu me rappeler d'appeler mamie ce soir", "appeler mamie"),
            ("Me rappeler de ranger le garage demain à 9h", "ranger le garage"),
            ("Rappelle-moi : faire les courses dans 30 minutes", "faire les courses"),
            ("Réveille-moi à 7h", "Réveil"),
        ):
            with self.subTest(text=text):
                result = parse_reminder_request(text)
                self.assertEqual(result["action"], "create_reminder")
                self.assertEqual(result["data"]["title"], expected_title)
                self.assertIn(result["data"]["when"], text)

    def test_when_hints(self):
        cases = (
            ("dans 1 heure", "dans 1 heure"),
            ("à 18h", "à 18h"),
            ("à 18h30", "à 18h30"),
            ("demain à 9h", "demain à 9h"),
            ("ce soir", "ce soir"),
            ("à midi", "à midi"),
        )
        for hint, expected in cases:
            with self.subTest(hint=hint):
                result = parse_reminder_request(f"Rappelle-moi de tester {hint}")
                self.assertEqual(result["data"]["when"], expected)

    def test_no_inference_without_time_or_intent(self):
        for text in (
            "Tu peux me rappeler mes rendez-vous ?",
            "Ne me rappelle pas de ranger le garage.",
            "Rappelle-moi de mettre la musique en pause",
            "Peux-tu me raconter une histoire ?",
            "Je pense à rappeler mamie ce soir",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_reminder_request(text), {"action": "none"})

    def test_reject_empty_and_long_titles(self):
        for text in (
            "Rappelle-moi dans 1 heure",
            "Rappelle-moi de dans 1 heure",
            "Rappelle-moi de " + "a" * 201 + " à 18h",
        ):
            with self.subTest(text=text):
                with self.assertRaises(InvalidReminderRequest):
                    parse_reminder_request(text)


class ReminderProposalFlowTests(TestCase):
    def propose(self, message):
        with patch("assistant.views.generate_reply_stream") as generate:
            response = self.client.post(
                reverse("chat-stream"),
                data=json.dumps({"message": message}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            events = [
                json.loads(line)
                for line in b"".join(response.streaming_content).decode().splitlines()
            ]
            generate.assert_not_called()
        self.assertEqual([event["type"] for event in events], ["start", "delta", "done"])
        return events[-1]["action_proposal"]

    def test_stream_proposes_reminder_without_creating_it(self):
        proposal = self.propose("Rappelle-moi de boire de l'eau dans 1 heure.")
        self.assertEqual(proposal["action"], "create_reminder")
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["data"]["title"], "boire de l'eau")
        self.assertEqual(proposal["data"]["when"], "dans 1 heure")
        self.assertEqual(Reminder.objects.count(), 0)

    def test_non_streaming_chat_proposes_reminder_too(self):
        response = self.client.post(
            reverse("chat"), data={"message": "Rappelle-moi d'éteindre le four à 20h"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action_proposal"]["action"], "create_reminder")
        self.assertEqual(Reminder.objects.count(), 0)

    def test_reminder_proposal_is_stored_and_visible_in_conversation(self):
        proposal = self.propose("Rappelle-moi de faire du sport demain à 18h")
        conversation = Conversation.objects.get()
        saved = ActionProposal.objects.get(pk=proposal["id"])
        self.assertEqual(saved.action, ActionProposal.Action.CREATE_REMINDER)
        response = self.client.get(
            reverse("conversation-detail", kwargs={"conversation_id": conversation.pk})
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["action_proposals"][0]
        self.assertEqual(result["id"], proposal["id"])
        self.assertEqual(result["data"]["title"], "faire du sport")

    @patch("assistant.views.generate_reply_stream")
    def test_ordinary_chat_is_unchanged(self, generate):
        generate.return_value = iter([("delta", "Bonjour"), ("done", "Bonjour")])
        response = self.client.post(
            reverse("chat-stream"),
            data=json.dumps({"message": "Bonjour"}),
            content_type="application/json",
        )
        events = [
            json.loads(line)
            for line in b"".join(response.streaming_content).decode().splitlines()
        ]
        self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)
        self.assertEqual(Reminder.objects.count(), 0)
