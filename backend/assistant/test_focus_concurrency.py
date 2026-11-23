import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import FocusSession, Task


def _close_worker_connections():
    """Libère les connexions ouvertes par un thread de travail (sinon le fichier
    de la base de test reste verrouillé sur Windows au moment de sa suppression)."""
    connections.close_all()


class FocusSessionConcurrencyTests(TransactionTestCase):
    """Requêtes réellement simultanées : un thread par requête, chacune avec sa
    propre connexion à la base de test.

    Nature de la base : SQLite ne permet qu'un seul écrivain à la fois (verrou
    d'écriture posé sur tout le fichier, délai d'attente de 20 s par défaut).
    Deux « vrais simultanés » s'exécutent donc en série au niveau de la base
    (pas d'écrasement de verrous), mais les protections appliquées restent
    nécessaires et sont exercées ici par de vraies requêtes concurrentes :
    - /complete/ idempotent : le résultat durable est écrit une seule fois,
      les répétitions (y compris simultanées) rejouent le même résultat ;
    - /undo/ : mise à jour conditionnelle sur updated_at + cycle de parcours,
      sinon une annulation écraserait silencieusement une modification
      concurrente ; un seul des participants à la course peut gagner.

    TransactionTestCase (sans transaction de test englobante) est obligatoire
    pour que les commits concurrents soient réels.
    """

    def _expired_session_with_task(self):
        task = Task.objects.create(title="Ranger le dépôt")
        session = FocusSession.objects.create(
            duration_minutes=25,
            phase=FocusSession.Phase.RUNNING,
            deadline=timezone.now() - timedelta(seconds=1),
            task=task,
        )
        return task, session

    def test_concurrent_complete_requests_are_idempotent(self):
        task, session = self._expired_session_with_task()

        def complete(_):
            client = Client()
            try:
                return client.post(
                    reverse("focus-session-complete", kwargs={"session_id": session.pk}),
                )
            finally:
                _close_worker_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(complete, range(4)))

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["reason"], "completed")
        self.assertIsNotNone(session)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DONE)
        session.refresh_from_db()
        self.assertEqual(session.outcome, FocusSession.Outcome.COMPLETED)
        self.assertEqual(session.completed_cycle, 1)
        # Un seul résultat durable écrit : l'outcome est toujours "completed".
        sessions = FocusSession.objects.filter(pk=session.pk)
        self.assertEqual(sessions.count(), 1)

    def test_concurrent_undo_has_single_winner(self):
        task, session = self._expired_session_with_task()
        complete = self.client.post(
            reverse("focus-session-complete", kwargs={"session_id": session.pk}),
        )
        self.assertEqual(complete.status_code, 200)
        session.refresh_from_db()
        cycle = session.completed_cycle
        self.assertEqual(cycle, 1)

        barrier = threading.Barrier(2)

        def undo(_):
            client = Client()
            barrier.wait()
            try:
                return client.post(
                    reverse("focus-session-undo", kwargs={"session_id": session.pk}),
                    data=json.dumps({"cycle": cycle}),
                    content_type="application/json",
                )
            finally:
                _close_worker_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            undo_a, undo_b = list(pool.map(undo, range(2)))

        statuses = sorted([undo_a.status_code, undo_b.status_code])
        # Un seul vainqueur : l'autre trouve soit "plus rien à annuler"
        # (outcome déjà passé à "undone"), soit la tâche déjà remise à faire.
        self.assertEqual(statuses, [200, 409])
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.TODO)
        session.refresh_from_db()
        self.assertEqual(session.outcome, FocusSession.Outcome.UNDONE)

    def test_concurrent_undo_vs_rename_never_loses_the_rename(self):
        """Annulation et renommage simultanés : aucune modification ne disparaît.

        Selon qui gagne la course :
        - l'annulation en premier → le renommage concurrent est refusé (version
          de tâche périmée) ; la tâche retombe « à faire » avec son titre initial ;
        - le renommage en premier → l'annulation refuse d'écraser une tâche dont
          la version a changé ; la tâche reste « faite » avec le nouveau titre.
        Dans les deux cas le résultat est cohérent et rien n'est perdu.
        """
        task, session = self._expired_session_with_task()
        self.assertEqual(
            self.client.post(
                reverse("focus-session-complete", kwargs={"session_id": session.pk}),
            ).status_code,
            200,
        )
        task.refresh_from_db()
        version = task.updated_at.isoformat()
        original_title = task.title

        barrier = threading.Barrier(2)

        def rename():
            client = Client()
            barrier.wait()
            try:
                return client.patch(
                    reverse("task-detail", kwargs={"task_id": task.pk}),
                    data=json.dumps({
                        "title": "Renommée en parallèle",
                        "expected_updated_at": version,
                    }),
                    content_type="application/json",
                )
            finally:
                _close_worker_connections()

        def undo():
            client = Client()
            barrier.wait()
            try:
                return client.post(
                    reverse("focus-session-undo", kwargs={"session_id": session.pk}),
                    data=json.dumps({"cycle": 1}),
                    content_type="application/json",
                )
            finally:
                _close_worker_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            rename_future = pool.submit(rename)
            undo_future = pool.submit(undo)
            rename_response = rename_future.result()
            undo_response = undo_future.result()

        # Un seul des deux a pu prévaloir.
        self.assertEqual(
            (rename_response.status_code == 200) + (undo_response.status_code == 200),
            1,
        )

        session.refresh_from_db()
        task.refresh_from_db()
        if undo_response.status_code == 200:
            # L'annulation a gagné : le renommage concurrent a été rejeté par la
            # vérification de version ; le titre d'origine est conservé.
            self.assertEqual(task.status, Task.Status.TODO)
            self.assertEqual(task.title, original_title)
            self.assertEqual(session.outcome, FocusSession.Outcome.UNDONE)
        else:
            # Le renommage a gagné : l'annulation refuse d'écraser la tâche
            # modifiée ; le nouveau titre est conservé.
            self.assertEqual(rename_response.status_code, 200)
            self.assertEqual(task.status, Task.Status.DONE)
            self.assertEqual(task.title, "Renommée en parallèle")
            self.assertEqual(session.outcome, FocusSession.Outcome.COMPLETED)
