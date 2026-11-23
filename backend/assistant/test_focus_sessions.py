import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import FocusSession, Task


class FocusSessionCreationTests(TestCase):
    def post_session(self, data):
        return self.client.post(
            reverse("focus-session-list"),
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_create_without_task(self):
        response = self.post_session({"duration_minutes": 25, "label": "Lire un papier"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["duration_minutes"], 25)
        self.assertEqual(body["label"], "Lire un papier")
        self.assertEqual(body["phase"], "idle")
        self.assertIsNone(body["task"])

    def test_create_with_task_links_it(self):
        task = Task.objects.create(title="Ranger mon bureau")
        response = self.post_session({
            "duration_minutes": 15,
            "label": "Ranger mon bureau",
            "task": task.pk,
        })
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["task"]["id"], task.pk)
        self.assertEqual(body["task"]["title"], "Ranger mon bureau")

    def test_create_with_unknown_task_rejected(self):
        response = self.post_session({"duration_minutes": 15, "task": 99999})
        self.assertEqual(response.status_code, 400)

    def test_create_without_duration_rejected(self):
        response = self.post_session({"label": "Sans durée"})
        self.assertEqual(response.status_code, 400)

    def test_create_does_not_require_remaining_time(self):
        # remaining_time_ms est optionnel à la création (rempli pendant le suivi).
        response = self.post_session({"duration_minutes": 5})
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["remaining_time_ms"])

    def test_same_endpoint_lists_and_creates(self):
        create = self.post_session({"duration_minutes": 25})
        self.assertEqual(create.status_code, 201)
        listing = self.client.get(reverse("focus-session-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

    def test_persisted_without_task_keeps_no_task_link(self):
        # Une session créée sans tâche reste sans tâche en base, et liste vide.
        response = self.post_session({"duration_minutes": 25})
        self.assertEqual(response.status_code, 201)
        session = FocusSession.objects.get(pk=response.json()["id"])
        self.assertIsNone(session.task)
        self.assertEqual(session.phase, FocusSession.Phase.IDLE)
        self.assertIsNone(session.outcome)


class FocusSessionTransitionTests(TestCase):
    """La phase est pilotée par le serveur : MIA calcule l'échéance."""

    def setUp(self):
        self.session = FocusSession.objects.create(duration_minutes=25)

    def patch(self, data):
        return self.client.patch(
            reverse("focus-session-detail", kwargs={"session_id": self.session.pk}),
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_start_uses_duration_ignoring_client_remaining(self):
        # L'autorité temporelle est côté serveur : au départ d'un nouveau
        # parcours, la durée de la session fait foi. Une valeur remaining_time_ms
        # envoyée par le client ne permet pas de raccourcir le parcours.
        before = timezone.now()
        response = self.patch({"phase": "running", "remaining_time_ms": 900000})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["phase"], "running")
        deadline = timezone.datetime.fromisoformat(body["deadline"].replace("Z", "+00:00"))
        # échéance ≈ maintenant + 25 min (durée de la session), pas + 15 min.
        self.assertAlmostEqual(
            (deadline - before).total_seconds(), 25 * 60, delta=5,
        )
        self.assertEqual(body["remaining_time_ms"], 25 * 60000)

    def test_start_ignores_null_or_negative_client_remaining(self):
        for bad_remaining in (0, -5, None, "abc"):
            self.session.refresh_from_db()
            self.session.phase = FocusSession.Phase.IDLE
            self.session.save(update_fields=["phase"])
            payload = {"phase": "running"}
            if bad_remaining is not None:
                payload["remaining_time_ms"] = bad_remaining
            response = self.patch(payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["remaining_time_ms"], 25 * 60000)

    def test_start_without_remaining_uses_duration(self):
        response = self.patch({"phase": "running"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remaining_time_ms"], 25 * 60000)

    def test_start_bumps_cycle(self):
        response = self.patch({"phase": "running"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cycle"], 1)

    def test_pause_computes_remaining_from_deadline(self):
        self.patch({"phase": "running", "remaining_time_ms": 900000})
        # le temps avance de 10 minutes
        FocusSession.objects.filter(pk=self.session.pk).update(
            deadline=timezone.now() + timedelta(minutes=5),
        )
        response = self.patch({"phase": "paused"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["phase"], "paused")
        self.assertIsNone(body["deadline"])
        self.assertGreater(body["remaining_time_ms"], 0)
        self.assertLessEqual(body["remaining_time_ms"], 900000)
        self.assertAlmostEqual(body["remaining_time_ms"], 300000, delta=2000)

    def test_pause_requires_running(self):
        response = self.patch({"phase": "paused"})
        self.assertEqual(response.status_code, 400)

    def test_resume_uses_stored_remaining(self):
        self.patch({"phase": "running", "remaining_time_ms": 900000})
        FocusSession.objects.filter(pk=self.session.pk).update(
            deadline=timezone.now() + timedelta(minutes=5),
        )
        self.patch({"phase": "paused"})
        response = self.patch({"phase": "running"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["phase"], "running")
        self.assertIsNotNone(body["deadline"])
        self.assertAlmostEqual(body["remaining_time_ms"], 300000, delta=2000)

    def test_resume_ignores_client_remaining_shorter_null_or_negative(self):
        # À la reprise, le serveur réutilise son propre restant enregistré,
        # quelle que soit la valeur envoyée par le client.
        for bad_remaining in (1, 0, -5, None, "abc"):
            FocusSession.objects.filter(pk=self.session.pk).update(
                phase=FocusSession.Phase.PAUSED,
                deadline=None,
                remaining_time_ms=300000,
            )
            payload = {"phase": "running"}
            if bad_remaining is not None:
                payload["remaining_time_ms"] = bad_remaining
            response = self.patch(payload)
            self.assertEqual(response.status_code, 200)
            self.assertAlmostEqual(response.json()["remaining_time_ms"], 300000, delta=2000)

    def test_resume_does_not_bump_cycle(self):
        self.patch({"phase": "running"})
        FocusSession.objects.filter(pk=self.session.pk).update(
            deadline=timezone.now() + timedelta(minutes=5),
        )
        self.patch({"phase": "paused"})
        self.session.refresh_from_db()
        before = self.session.cycle
        response = self.patch({"phase": "running"})
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.cycle, before)

    def test_finished_cannot_be_set_by_patch(self):
        for phase in ("finished", "idle"):
            response = self.patch({"phase": phase})
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.json()["error"])

    def test_metadata_rejected_while_running(self):
        self.patch({"phase": "running", "remaining_time_ms": 900000})
        response = self.patch({"label": "nouveau"})
        self.assertEqual(response.status_code, 400)

    def test_restart_after_finished_resets_outcome(self):
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.FINISHED,
            outcome=FocusSession.Outcome.COMPLETED,
            completed_at=timezone.now(),
        )
        response = self.client.patch(
            reverse("focus-session-detail", kwargs={"session_id": session.pk}),
            data=json.dumps({"phase": "running", "remaining_time_ms": 1500000}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.phase, FocusSession.Phase.RUNNING)
        self.assertIsNone(session.outcome)
        self.assertIsNone(session.completed_at)


class FocusSessionCompletionTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(title="Préparer la réunion")
        self.other_task = Task.objects.create(title="Autre tâche")

    def complete(self, session):
        return self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": session.pk}),
        )

    def undo(self, session):
        session.refresh_from_db()
        return self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": session.pk}),
            data=json.dumps({"cycle": session.completed_cycle}),
            content_type="application/json",
        )

    def expire(self, session):
        # Simule l'échéance atteinte côté serveur.
        FocusSession.objects.filter(pk=session.pk).update(
            deadline=timezone.now() - timedelta(seconds=1),
        )

    def test_complete_marks_linked_task_done(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reason"], "completed")
        self.assertEqual(body["outcome"], FocusSession.Outcome.COMPLETED)
        self.assertTrue(body["task_completed"])
        self.assertEqual(body["task"]["status"], "done")
        # L'instant de marquage et le cycle concerné sont renvoyés : la fenêtre
        # d'annulation s'appuie dessus (pas de renouvellement au rechargement).
        self.assertIsNotNone(body["completed_at"])
        session.refresh_from_db()
        self.assertEqual(body["cycle"], session.completed_cycle)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_complete_accepts_running_with_expired_deadline(self):
        # rechargement après l'échéance : le client n'a pas pu signaler la fin,
        # mais MIA constate que le délai est écoulé.
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.RUNNING,
            task=self.task,
            deadline=timezone.now() + timedelta(seconds=30),
        )
        self.expire(session)
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "completed")
        session.refresh_from_db()
        self.assertEqual(session.phase, FocusSession.Phase.FINISHED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_complete_on_running_session_with_future_deadline_rejected(self):
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.RUNNING,
            task=self.task,
            deadline=timezone.now() + timedelta(minutes=5),
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_complete_on_idle_session_rejected(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.IDLE, task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_complete_on_paused_with_remaining_rejected(self):
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.PAUSED,
            remaining_time_ms=600000,
            task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 400)

    def test_complete_on_paused_at_zero_accepted(self):
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.PAUSED,
            remaining_time_ms=0,
            task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "completed")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_complete_when_task_already_done(self):
        self.task.status = Task.Status.DONE
        self.task.save(update_fields=["status"])
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reason"], "already_done")
        # La tâche n'a pas été modifiée par cette session.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_complete_after_task_deleted_does_nothing(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        self.task.delete()  # SET_NULL → le lien de la session est rompu
        session.refresh_from_db()
        self.assertIsNone(session.task)
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "no_task")
        self.assertIsNone(response.json()["task"])

    def test_complete_has_no_effect_on_other_task(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        response = self.complete(session)
        self.assertEqual(response.status_code, 200)
        self.other_task.refresh_from_db()
        self.assertEqual(self.other_task.status, Task.Status.TODO)

    def test_complete_is_idempotent(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        first = self.complete(session)
        self.assertEqual(first.status_code, 200)
        self.task.refresh_from_db()
        done_at = self.task.updated_at
        second = self.complete(session)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["reason"], "completed")
        self.assertEqual(second.json()["outcome"], FocusSession.Outcome.COMPLETED)
        # Aucun second effet : la tâche n'a pas été re-sauvegardée.
        self.task.refresh_from_db()
        self.assertEqual(self.task.updated_at, done_at)
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_complete_after_undo_since_reload_keeps_task_todo(self):
        # scénario obligatoire : fin → marquage → annulation → rechargement →
        # rappel de /complete/ → la tâche reste à faire.
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        self.assertEqual(self.complete(session).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertEqual(self.undo(session).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

        # "rechargement" : on rappelle /complete/ comme au démarrage de la page.
        replay = self.complete(session)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["reason"], "undone")
        self.assertFalse(replay.json()["task_completed"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_complete_replays_renamed_task(self):
        session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )
        self.complete(session)
        self.task.title = "Préparer la réunion (réunion déplacée)"
        self.task.save(update_fields=["title"])
        replay = self.complete(session)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["reason"], "completed")
        self.assertEqual(replay.json()["task"]["title"], "Préparer la réunion (réunion déplacée)")

    def test_complete_on_missing_session_returns_404(self):
        response = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": 99999}),
        )
        self.assertEqual(response.status_code, 404)


class FocusSessionUndoTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(title="Ranger les papiers")
        self.session = FocusSession.objects.create(
            duration_minutes=25, phase=FocusSession.Phase.FINISHED, task=self.task,
        )

    def undo(self):
        self.session.refresh_from_db()
        return self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"cycle": self.session.completed_cycle}),
            content_type="application/json",
        )

    def undo_without_cycle(self):
        return self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
        )

    def complete(self):
        return self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )

    def test_undo_requires_previous_marking(self):
        # Pas de marquage effectué par la session → rien à annuler.
        self.session.outcome = FocusSession.Outcome.ALREADY_DONE
        self.session.save(update_fields=["outcome"])
        response = self.undo_without_cycle()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"])

    def test_undo_without_cycle_rejected(self):
        # Le cycle du marquage doit accompagner la demande d'annulation.
        self.complete()
        response = self.undo_without_cycle()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"])

    def test_undo_with_wrong_cycle_rejected(self):
        self.complete()
        self.session.refresh_from_db()
        wrong = (self.session.completed_cycle or 0) + 1
        response = self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"cycle": wrong}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.task.refresh_from_db()
        # Le marquage d'origine reste en place.
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_undo_after_complete_restores_task(self):
        self.complete()
        response = self.undo()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reason"], "undone")
        self.assertEqual(body["task"]["status"], "todo")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)
        self.session.refresh_from_db()
        self.assertEqual(self.session.outcome, FocusSession.Outcome.UNDONE)

    def test_undo_repeated_is_rejected(self):
        self.complete()
        self.assertEqual(self.undo().status_code, 200)
        # La session n'a plus de marquage actif : seconde annulation refusée.
        response = self.undo()
        self.assertEqual(response.status_code, 409)

    def test_undo_refused_when_task_changed(self):
        self.complete()
        # Modification concurrente (par ex. renommage via le panneau) : la route
        # métier force updated_at, la version de tâche enregistrée ne matche plus.
        self.task.refresh_from_db()
        response = self.client.patch(
            reverse("task-detail", kwargs={"task_id": self.task.pk}),
            data=json.dumps({
                "title": "Renommée entretemps",
                "expected_updated_at": self.task.updated_at.isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        undo = self.undo()
        self.assertEqual(undo.status_code, 409)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_undo_refused_when_task_is_todo_already(self):
        self.complete()
        self.task.status = Task.Status.TODO
        self.task.save(update_fields=["status"])
        response = self.undo()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"])

    def test_undo_refused_when_task_deleted(self):
        self.complete()
        self.task.delete()  # SET_NULL : le lien de la session est rompu
        self.session.refresh_from_db()
        self.assertIsNone(self.session.task)
        response = self.undo()
        self.assertEqual(response.status_code, 409)

    def test_undo_on_missing_session_returns_404(self):
        response = self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": 99999}),
        )
        self.assertEqual(response.status_code, 404)


class FocusSessionResetTests(TestCase):
    """Le reset remet l'horloge ET le résultat durable à zéro, sans toucher à la tâche."""

    def setUp(self):
        self.task = Task.objects.create(title="Préparer l'avion")
        self.session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.RUNNING,
            deadline=timezone.now() + timedelta(minutes=15),
            task=self.task,
        )

    def reset(self, session=None):
        pk = (session or self.session).pk
        return self.client.post(
            reverse("focus-session-reset", kwargs={"session_id": pk}),
        )

    def test_reset_returns_idle_and_clears_clock(self):
        response = self.reset()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["phase"], "idle")
        self.assertIsNone(body["deadline"])
        self.assertIsNone(body["remaining_time_ms"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, FocusSession.Phase.IDLE)
        self.assertIsNone(self.session.deadline)
        self.assertIsNone(self.session.remaining_time_ms)
        # La tâche n'est pas touchée par le reset.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_reset_clears_recorded_outcome(self):
        self.session.phase = FocusSession.Phase.FINISHED
        self.session.outcome = FocusSession.Outcome.COMPLETED
        self.session.completed_at = timezone.now()
        self.session.marked_task_version = self.task.updated_at
        self.session.save(update_fields=[
            "phase", "outcome", "completed_at", "marked_task_version",
        ])
        response = self.reset()
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, FocusSession.Phase.IDLE)
        self.assertIsNone(self.session.outcome)
        self.assertIsNone(self.session.completed_at)
        self.assertIsNone(self.session.marked_task_version)
        # L'annulation de l'ancien marquage n'est plus possible après reset.
        undo = self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(undo.status_code, 409)

    def test_reset_then_run_then_complete_marks_again(self):
        # Après reset, un nouveau parcours complet re-marque la tâche.
        response = self.reset()
        self.assertEqual(response.status_code, 200)
        patch = self.client.patch(
            reverse("focus-session-detail", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"phase": "running", "remaining_time_ms": 2500}),
            content_type="application/json",
        )
        self.assertEqual(patch.status_code, 200)
        FocusSession.objects.filter(pk=self.session.pk).update(
            deadline=timezone.now() - timedelta(seconds=1),
        )
        complete = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()["reason"], "completed")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.session.refresh_from_db()
        self.assertEqual(self.session.outcome, FocusSession.Outcome.COMPLETED)

    def test_stale_complete_after_reset_has_no_effect(self):
        # Une ancienne demande /complete/ rejouée après un reset ne marque rien.
        self.session.phase = FocusSession.Phase.FINISHED
        self.session.save(update_fields=["phase", "completed_at"])
        first = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["reason"], "completed")
        self.task.refresh_from_db()
        done_at = self.task.updated_at
        self.assertEqual(self.task.status, Task.Status.DONE)

        self.reset()
        # La session est de nouveau "idle" : la complétion prématurée est rejetée,
        # la tâche n'est pas re-sauvegardée et aucun résultat n'est enregistré.
        replay = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(replay.status_code, 400)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.outcome)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertEqual(self.task.updated_at, done_at)

    def test_reset_bumps_cycle(self):
        first_start = self.client.patch(
            reverse("focus-session-detail", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"phase": "running"}),
            content_type="application/json",
        )
        self.assertEqual(first_start.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.cycle, 1)
        self.reset()
        self.session.refresh_from_db()
        self.assertEqual(self.session.cycle, 2)

    def test_stale_undo_from_previous_cycle_after_new_completion_rejected(self):
        # scénario : parcours 1 marqué → reset → nouveau parcours qui re-marque →
        # une demande d'annulation du parcours 1 (rejouée tardivement) ne doit
        # pas modifier le résultat du parcours 2.
        self.session.phase = FocusSession.Phase.IDLE
        self.session.save(update_fields=["phase"])
        # parcours 1 : complétion directe (cycle 0 sur session jamais lancée).
        self.session.phase = FocusSession.Phase.FINISHED
        self.session.save(update_fields=["phase"])
        c1 = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(c1.status_code, 200)
        self.session.refresh_from_db()
        first_cycle = self.session.completed_cycle
        self.assertIsNotNone(first_cycle)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

        # reset → la tâche redevient "à faire" (comme après un vrai cycle).
        self.reset()
        self.task.status = Task.Status.TODO
        self.task.save(update_fields=["status"])

        # parcours 2 : nouveau lancé + échéance atteinte + complétion.
        patch = self.client.patch(
            reverse("focus-session-detail", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"phase": "running"}),
            content_type="application/json",
        )
        self.assertEqual(patch.status_code, 200)
        FocusSession.objects.filter(pk=self.session.pk).update(
            deadline=timezone.now() - timedelta(seconds=1),
        )
        c2 = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": self.session.pk}),
        )
        self.assertEqual(c2.status_code, 200)
        self.assertEqual(c2.json()["reason"], "completed")
        self.session.refresh_from_db()
        second_cycle = self.session.completed_cycle
        self.assertNotEqual(second_cycle, first_cycle)

        # La demande d'annulation du parcours 1 est ignorée.
        stale = self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"cycle": first_cycle}),
            content_type="application/json",
        )
        self.assertEqual(stale.status_code, 409)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.session.refresh_from_db()
        self.assertEqual(self.session.outcome, FocusSession.Outcome.COMPLETED)

        # La demande courante (parcours 2) fonctionne toujours.
        current = self.client.post(
            reverse("focus-session-undo", kwargs={"session_id": self.session.pk}),
            data=json.dumps({"cycle": second_cycle}),
            content_type="application/json",
        )
        self.assertEqual(current.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_reset_on_missing_session_returns_404(self):
        response = self.client.post(
            reverse("focus-session-reset", kwargs={"session_id": 99999}),
        )
        self.assertEqual(response.status_code, 404)

