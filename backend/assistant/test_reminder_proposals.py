import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ActionProposal, Conversation, Reminder
from .reminder_rules import InvalidReminderRequest, interpret_when, parse_reminder_request


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


class InterpretWhenTests(TestCase):
    def assertFuture(self, hint, hours, minutes=0):
        now = timezone.now()
        due = interpret_when(hint, now=now)
        self.assertGreater(due, now, f"{hint!r} doit être dans le futur")
        delta = due - now
        self.assertAlmostEqual(
            delta.total_seconds() / 3600, hours + minutes / 60, delta=0.5
        )

    def test_relative_delays(self):
        self.assertFuture("dans 1 heure", 1)
        self.assertFuture("dans 30 minutes", 0, 30)
        self.assertFuture("dans 2 jours", 48)

    def test_absolute_clock_is_future(self):
        # « à 7h » demande à 10h désigne demain : toujours dans le futur.
        now = timezone.now()
        due = interpret_when("à 7h", now=now)
        self.assertGreater(due, now)

    def test_unknown_falls_back_to_one_hour(self):
        self.assertFuture("", 1)

    def test_noon_vs_afternoon_not_confused(self):
        now = timezone.now()
        midday = interpret_when("à midi", now=now)
        afternoon = interpret_when("cet après-midi", now=now)
        self.assertEqual(midday.hour, 12)
        self.assertEqual(afternoon.hour, 15)


class ReminderDirectFlowTests(TestCase):
    def stream_events(self, message):
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
        return events

    def test_stream_creates_reminder_directly(self):
        events = self.stream_events("Rappelle-moi de boire de l'eau dans 1 heure.")
        reminder = events[-1]["reminder"]
        self.assertEqual(reminder["title"], "boire de l'eau")
        self.assertEqual(Reminder.objects.count(), 1)
        saved = Reminder.objects.get()
        self.assertEqual(saved.title, "boire de l'eau")
        self.assertGreater(saved.due_at, timezone.now())
        self.assertIn("boire de l'eau", events[-2]["content"])
        # Plus aucune proposition à confirmer.
        self.assertNotIn("action_proposal", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)

    def test_reveil_title(self):
        events = self.stream_events("Réveille-moi à 7h")
        self.assertEqual(events[-1]["reminder"]["title"], "Réveil")
        self.assertGreater(Reminder.objects.get().due_at, timezone.now())

    def test_non_streaming_chat_creates_reminder_too(self):
        response = self.client.post(
            reverse("chat"), data={"message": "Rappelle-moi d'éteindre le four à 20h"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reminder"]["title"], "éteindre le four")
        self.assertIn("éteindre le four", body["reply"])
        self.assertEqual(Reminder.objects.count(), 1)

    def test_conversation_has_both_messages(self):
        self.stream_events("Rappelle-moi de faire du sport demain à 18h")
        conversation = Conversation.objects.get()
        roles = [
            m.role for m in conversation.messages.order_by("created_at", "id")
        ]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(Reminder.objects.count(), 1)

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
        self.assertNotIn("reminder", events[-1])
        self.assertEqual(ActionProposal.objects.count(), 0)
        self.assertEqual(Reminder.objects.count(), 0)

    def test_list_shows_created_reminder(self):
        self.stream_events("Rappelle-moi de payer la facture demain à 9h")
        response = self.client.get(reverse("reminder-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["title"], "payer la facture")
