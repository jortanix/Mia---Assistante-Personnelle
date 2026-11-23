from django.test import TestCase
from rest_framework.exceptions import ValidationError

from .models import ActionProposal, Conversation, Memory, Message
from .views import _resolve_cancel, _resolve_confirm
from django.urls import reverse


class MemoryConfirmationTests(TestCase):
    def setUp(self):
        conversation = Conversation.objects.create()
        message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content="Veux-tu que je retienne cette préférence ?",
        )
        self.proposal = ActionProposal.objects.create(
            conversation=conversation,
            assistant_message=message,
            action=ActionProposal.Action.SAVE_MEMORY,
            data={"content": "Je préfère avancer une étape à la fois."},
        )

    def test_pending_proposal_creates_no_memory(self):
        self.assertEqual(Memory.objects.count(), 0)
        self.assertIsNone(self.proposal.memory_id)

    def test_confirmation_creates_memory_only_once(self):
        proposal, confirmed = _resolve_confirm(self.proposal.pk)

        self.assertTrue(confirmed)
        self.assertEqual(proposal.status, ActionProposal.Status.CONFIRMED)
        self.assertEqual(
            proposal.memory.content,
            self.proposal.data["content"],
        )
        memory_id = proposal.memory_id

        proposal, confirmed = _resolve_confirm(self.proposal.pk)

        self.assertTrue(confirmed)
        self.assertEqual(Memory.objects.count(), 1)
        self.assertEqual(proposal.memory_id, memory_id)

    def test_cancelled_proposal_cannot_be_confirmed(self):
        self.proposal.status = ActionProposal.Status.CANCELLED
        self.proposal.save(update_fields=["status"])

        proposal, confirmed = _resolve_confirm(self.proposal.pk)

        self.assertFalse(confirmed)
        self.assertEqual(proposal.status, ActionProposal.Status.CANCELLED)
        self.assertEqual(Memory.objects.count(), 0)

    def test_invalid_content_keeps_proposal_pending(self):
        self.proposal.data = {"content": ""}
        self.proposal.save(update_fields=["data"])

        with self.assertRaises(ValidationError):
            _resolve_confirm(self.proposal.pk)

        self.proposal.refresh_from_db()
        self.assertEqual(
            self.proposal.status,
            ActionProposal.Status.PENDING,
        )
        self.assertEqual(Memory.objects.count(), 0)
    def test_cancellation_blocks_later_confirmation(self):
        proposal, cancelled = _resolve_cancel(self.proposal.pk)

        self.assertTrue(cancelled)
        self.assertEqual(proposal.status, ActionProposal.Status.CANCELLED)
        self.assertEqual(Memory.objects.count(), 0)

        proposal, confirmed = _resolve_confirm(self.proposal.pk)

        self.assertFalse(confirmed)
        self.assertEqual(Memory.objects.count(), 0)

        proposal, cancelled = _resolve_cancel(self.proposal.pk)
        self.assertTrue(cancelled)

    def test_confirmed_proposal_cannot_be_cancelled(self):
        proposal, confirmed = _resolve_confirm(self.proposal.pk)
        memory_id = proposal.memory_id

        proposal, cancelled = _resolve_cancel(self.proposal.pk)

        self.assertTrue(confirmed)
        self.assertFalse(cancelled)
        self.assertEqual(proposal.status, ActionProposal.Status.CONFIRMED)
        self.assertEqual(proposal.memory_id, memory_id)
        self.assertEqual(Memory.objects.count(), 1)
    def test_confirmation_endpoint(self):
        url = reverse(
            "action-proposal-confirm",
            kwargs={"proposal_id": self.proposal.pk},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "confirmed")
        self.assertEqual(
            response.json()["memory"]["content"],
            self.proposal.data["content"],
        )
        self.assertEqual(Memory.objects.count(), 1)

        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Memory.objects.count(), 1)

    def test_cancellation_endpoint_blocks_confirmation(self):
        cancel_url = reverse(
            "action-proposal-cancel",
            kwargs={"proposal_id": self.proposal.pk},
        )
        confirm_url = reverse(
            "action-proposal-confirm",
            kwargs={"proposal_id": self.proposal.pk},
        )

        response = self.client.post(cancel_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertIsNone(response.json()["memory"])

        response = self.client.post(confirm_url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Memory.objects.count(), 0)

