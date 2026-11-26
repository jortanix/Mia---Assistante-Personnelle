import json
import os
import secrets
import tempfile
from datetime import timedelta

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from .models import (
    ActionProposal,
    BrainrotEvent,
    Conversation,
    Memory,
    Message,
    Reminder,
    Task,
    FocusSession,
)
from .serializers import (
    ActionProposalSerializer,
    BrainrotSerializer,
    MemorySerializer,
    ChatRequestSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    ConversationUpdateSerializer,
    ReminderSerializer,
    TaskSerializer,
    FocusSessionSerializer,
    FocusSessionCreateSerializer,
    FocusSessionUpdateSerializer,
)
from .services import (
    InvalidActionAnalysis,
    OllamaResponseError,
    OllamaUnavailableError,
    analyze_action,
    generate_reply,
    generate_reply_stream,
)
from .memory_rules import detect_memory_preference
from .reminder_rules import InvalidReminderRequest, interpret_when, parse_reminder_request
from .task_rules import InvalidTaskRequest, parse_task_request
from .task_queries import build_task_answer
from .transcription import (
    TranscriptionError,
    TranscriptionUnavailableError,
    get_audio_duration,
    transcribe_audio,
)
from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from briefing.detect import is_daily_briefing_request
from briefing.service import provide_daily_briefing, structured_briefing

HISTORY_LIMIT = 12
DEFAULT_TITLE = "Nouvelle conversation"
AUTO_TITLE_MAX = 60


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def conversation_list(request):
    conversations = Conversation.objects.all()
    serializer = ConversationSerializer(conversations, many=True)
    return Response(serializer.data)


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(
        Conversation,
        pk=conversation_id,
    )

    if request.method == "GET":
        serializer = ConversationDetailSerializer(conversation)
        return Response(serializer.data)

    if request.method == "PATCH":
        serializer = ConversationUpdateSerializer(
            conversation,
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ConversationSerializer(conversation).data)

    conversation.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def task_list(request):
    tasks = Task.objects.all()
    return Response(TaskSerializer(tasks, many=True).data)


@api_view(["PATCH", "DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def task_detail(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    expected = request.data.get("expected_updated_at")
    if expected is None:
        expected_date = task.updated_at
    else:
        try:
            expected_date = parse_datetime(expected) if isinstance(expected, str) else None
        except (ValueError, TypeError, OverflowError):
            expected_date = None
        if expected_date is None or timezone.is_naive(expected_date):
            return Response(
                {"error": "Version de tâche invalide. Actualise la liste."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    current = Task.objects.filter(pk=task_id, updated_at=expected_date)
    if request.method == "PATCH":
        serializer = TaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values["updated_at"] = timezone.now()
        updated = current.update(**values)
        if not updated:
            return Response(
                {"error": "Cette tâche a changé ou a été supprimée. Annule la modification et actualise la liste avant de réessayer."},
                status=status.HTTP_409_CONFLICT,
            )
        task.refresh_from_db()
        return Response(TaskSerializer(task).data)

    claimed = current.update(updated_at=timezone.now())
    if not claimed:
        return Response(
            {"error": "Cette tâche a changé. Actualise la liste avant de confirmer sa suppression."},
            status=status.HTTP_409_CONFLICT,
        )
    task.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def reminder_list(request):
    """Rappels planifiés (notifications de l'app mobile).

    - ``GET`` : liste de tous les rappels ;
    - ``POST`` : crée un rappel (``title``, ``due_at``, ``done``, ``repeat``).
    """
    if request.method == "POST":
        serializer = ReminderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    reminders = Reminder.objects.all()
    return Response(ReminderSerializer(reminders, many=True).data)


@api_view(["PATCH", "DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def reminder_detail(request, reminder_id):
    """Met à jour (``PATCH``, ex. ``done``) ou supprime (``DELETE``) un rappel."""
    reminder = get_object_or_404(Reminder, pk=reminder_id)
    if request.method == "PATCH":
        serializer = ReminderSerializer(reminder, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ReminderSerializer(reminder).data)
    reminder.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def action_proposal_confirm(request, proposal_id):
    get_object_or_404(ActionProposal, pk=proposal_id)
    proposal, confirmed = _resolve_confirm(proposal_id)
    if not confirmed:
        return Response(
            {"error": "Cette proposition a été annulée et ne peut pas être confirmée."},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(ActionProposalSerializer(proposal).data)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def action_proposal_cancel(request, proposal_id):
    get_object_or_404(ActionProposal, pk=proposal_id)
    proposal, cancelled = _resolve_cancel(proposal_id)
    if not cancelled:
        return Response(
            {"error": "Cette proposition a déjà été résolue."},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(ActionProposalSerializer(proposal).data)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def memory_list(request):
    memories = Memory.objects.order_by("-confirmed_at", "-id")
    return Response(MemorySerializer(memories, many=True).data)


@api_view(["DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def memory_detail(request, memory_id):
    memory = get_object_or_404(Memory, pk=memory_id)
    memory.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def brainrot_list(request):
    """Liste les « cédages » au brainrot, ou en enregistre un nouveau."""
    if request.method == "GET":
        events = BrainrotEvent.objects.order_by("-created_at", "-id")
        return Response(BrainrotSerializer(events, many=True).data)

    serializer = BrainrotSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def brainrot_detail(request, event_id):
    event = get_object_or_404(BrainrotEvent, pk=event_id)
    event.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def chat(request):
    serializer = ChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    message = data["message"]

    conversation = _get_or_create_conversation(data.get("conversation_id"))
    history = _load_history(conversation)

    task_reply = build_task_answer(message)
    if task_reply is not None:
        _save_messages(conversation, message, task_reply)
        return Response({"conversation_id": conversation.pk, "reply": task_reply})

    if is_daily_briefing_request(message):
        reply = provide_daily_briefing()
        _save_messages(conversation, message, reply)
        return Response({"conversation_id": conversation.pk, "reply": reply})

    analysis = _run_action_analysis(message)

    if analysis.get("action") == "create_task":
        assistant_message, task = _create_task_direct(conversation, message, analysis)
        return Response(
            {
                "conversation_id": conversation.pk,
                "reply": assistant_message.content,
                "task": TaskSerializer(task).data,
            }
        )

    reminder_analysis = _run_reminder_analysis(message)
    if reminder_analysis.get("action") == "create_reminder":
        assistant_message, reminder = _create_reminder_direct(conversation, message, reminder_analysis)
        return Response(
            {
                "conversation_id": conversation.pk,
                "reply": assistant_message.content,
                "reminder": ReminderSerializer(reminder).data,
            }
        )

    try:
        reply = generate_reply(message, history=history, use_memory=data.get("use_memory", False))
    except OllamaUnavailableError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OllamaResponseError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    _save_messages(conversation, message, reply)

    return Response(
        {
            "conversation_id": conversation.pk,
            "reply": reply,
        }
    )


def _encode_stream_event(event_type: str, **data) -> str:
    payload = {"type": event_type, **data}
    return json.dumps(payload, ensure_ascii=False) + "\n"


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def chat_stream(request):
    serializer = ChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    message = data["message"]

    conversation = _get_or_create_conversation(data.get("conversation_id"))
    history = _load_history(conversation)
    conversation_id = conversation.pk

    def stream():
        yield _encode_stream_event("start", conversation_id=conversation_id)

        try:
            task_reply = build_task_answer(message)
            if task_reply is not None:
                _save_messages(conversation, message, task_reply)
                yield _encode_stream_event("delta", content=task_reply)
                yield _encode_stream_event("done", conversation_id=conversation_id)
                return

            if is_daily_briefing_request(message):
                reply = provide_daily_briefing()
                _save_messages(conversation, message, reply)
                yield _encode_stream_event("delta", content=reply)
                yield _encode_stream_event("done", conversation_id=conversation_id)
                return

            analysis = _run_action_analysis(message)
            if analysis.get("action") == "create_task":
                assistant_message, task = _create_task_direct(conversation, message, analysis)
                yield _encode_stream_event("delta", content=assistant_message.content)
                yield _encode_stream_event(
                    "done",
                    conversation_id=conversation_id,
                    task=TaskSerializer(task).data,
                )
                return

            reminder_analysis = _run_reminder_analysis(message)
            if reminder_analysis.get("action") == "create_reminder":
                assistant_message, reminder = _create_reminder_direct(conversation, message, reminder_analysis)
                yield _encode_stream_event("delta", content=assistant_message.content)
                yield _encode_stream_event(
                    "done",
                    conversation_id=conversation_id,
                    reminder=ReminderSerializer(reminder).data,
                )
                return

            preference = detect_memory_preference(message)
            if preference is not None:
                proposal = _create_memory_proposal_turn(conversation, message, preference)
                reply = proposal.assistant_message.content
                yield _encode_stream_event("delta", content=reply)
                yield _encode_stream_event(
                    "done",
                    conversation_id=conversation_id,
                    action_proposal=ActionProposalSerializer(proposal).data,
                )
                return

            for event_type, value in generate_reply_stream(message, history=history, use_memory=data.get("use_memory", False)):
                if event_type == "delta":
                    yield _encode_stream_event("delta", content=value)
                elif event_type == "done":
                    reply = value
                    _save_messages(conversation, message, reply)
                    yield _encode_stream_event("done", conversation_id=conversation_id)
        except ValidationError as exc:
            detail = exc.detail
            message_text = detail.get("error", "Proposition invalide.") if isinstance(detail, dict) else "Proposition invalide."
            yield _encode_stream_event("error", message=str(message_text))
        except OllamaUnavailableError as exc:
            yield _encode_stream_event("error", message=str(exc))
        except OllamaResponseError as exc:
            yield _encode_stream_event("error", message=str(exc))
        except Exception:
            yield _encode_stream_event(
                "error",
                message="Une erreur est survenue pendant la génération.",
            )

    return StreamingHttpResponse(
        stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def focus_session_list(request):
    """Collection des sessions de concentration : liste (GET) et création (POST)."""
    if request.method == "POST":
        serializer = FocusSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(
            FocusSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )

    sessions = FocusSession.objects.all()
    serializer = FocusSessionSerializer(sessions, many=True)
    return Response(serializer.data)


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def focus_session_detail(request, session_id):
    """Gère une session de concentration spécifique.

    PATCH accepte deux usages :
    - une transition d'horloge : {"phase": "running", "remaining_time_ms": N}
      (départ ou reprise) ou {"phase": "paused"} (pause : le serveur calcule le
      temps restant depuis son échéance) ;
    - une mise à jour d'intitulé ou de durée sur une session non commencée.
    Le passage à "finished" ne se fait que par l'assistant (/complete/),
    jamais par un PATCH direct.
    """
    session = get_object_or_404(FocusSession, pk=session_id)

    if request.method == "GET":
        return Response(FocusSessionSerializer(session).data)

    if request.method == "PATCH":
        phase = request.data.get("phase")
        if phase is not None:
            error = _apply_focus_transition(session, phase, request.data)
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
            session.refresh_from_db()
            return Response(FocusSessionSerializer(session).data)

        if session.phase in (FocusSession.Phase.RUNNING, FocusSession.Phase.PAUSED):
            return Response(
                {"error": "La session est en cours : son intitulé et sa durée ne peuvent pas être modifiés."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = FocusSessionUpdateSerializer(session, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(FocusSessionSerializer(session).data)

    session.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def _apply_focus_transition(session, phase, data):
    """Applique une transition d'horloge en prenant le serveur pour référence.

    Retourne None en cas de succès, sinon un message d'erreur.
    """
    now = timezone.now()

    if phase == FocusSession.Phase.PAUSED:
        if session.phase != FocusSession.Phase.RUNNING or session.deadline is None:
            return "La session n'est pas en cours : impossible de la mettre en pause."
        remaining_ms = max(0, int((session.deadline - now).total_seconds() * 1000))
        session.remaining_time_ms = remaining_ms
        session.deadline = None
        session.phase = FocusSession.Phase.PAUSED
        session.save(update_fields=["phase", "deadline", "remaining_time_ms", "updated_at"])
        return None

    if phase == FocusSession.Phase.RUNNING:
        if session.phase == FocusSession.Phase.PAUSED and session.remaining_time_ms is not None:
            # Reprise : le serveur reprend son propre restant enregistré, quelle
            # que soit la valeur envoyée par le client (nulle, négative ou
            # inférieure au restant : elle est ignorée).
            remaining_ms = session.remaining_time_ms
            fresh_cycle = False
        else:
            # Nouveau parcours (départ ou relance) : la durée fait autorité côté
            # serveur. remaining_time_ms envoyé par le client est ignoré, sinon
            # il pourrait raccourcir arbitrairement sa session.
            remaining_ms = session.duration_minutes * 60000
            fresh_cycle = True
        if remaining_ms is None:
            return "Durée restante introuvable : relance la session depuis le début."
        if remaining_ms == 0:
            return "Le minuteur est déjà à zéro : termine la session à l'écran."
        if fresh_cycle:
            # Nouveau parcours : nouveau numéro de cycle, résultat antérieur
            # (s'il existait) invalidé.
            session.cycle = (session.cycle or 0) + 1
            session.outcome = None
            session.completed_at = None
            session.marked_task_version = None
            session.completed_cycle = None
        session.phase = FocusSession.Phase.RUNNING
        session.deadline = now + timedelta(milliseconds=remaining_ms)
        session.remaining_time_ms = remaining_ms
        session.save(update_fields=[
            "phase", "deadline", "remaining_time_ms", "cycle",
            "outcome", "completed_at", "marked_task_version", "completed_cycle", "updated_at",
        ])
        return None

    if phase in (FocusSession.Phase.FINISHED, FocusSession.Phase.IDLE):
        return "Ce passage se fait automatiquement : termine la session à l'écran."

    return "Phase inconnue."


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def focus_session_reset(request, session_id):
    """Remet une session à zéro (début de décompte), sans toucher à la tâche.

    Un reset n'est pas un changement de phase : il annule le suivi temporel de
    la session et son résultat éventuel, pour repartir d'un parcours vierge.
    """
    session = get_object_or_404(FocusSession, pk=session_id)
    session.phase = FocusSession.Phase.IDLE
    session.deadline = None
    session.remaining_time_ms = None
    session.outcome = None
    session.completed_at = None
    session.marked_task_version = None
    session.completed_cycle = None
    # Un parcours vierge repart avec un nouveau numéro de cycle : les demandes
    # d'annulation du parcours précédent (rejouées ou tardives) seront ignorées.
    session.cycle = (session.cycle or 0) + 1
    session.save(update_fields=[
        "phase", "deadline", "remaining_time_ms", "cycle",
        "outcome", "completed_at", "marked_task_version", "completed_cycle", "updated_at",
    ])
    return Response(FocusSessionSerializer(session).data)


def _focus_completion_response(session):
    """Réponse de complétion/idempotente, dérivée du résultat durable.

    Inclut completed_at (le moment exact du marquage) et le numéro du parcours
    concerné : le client en déduit la fenêtre d'annulation (qui n'est pas
    renouvelée par un rechargement) et la renvoie avec toute demande
    d'annulation pour éviter qu'une requête d'un ancien parcours n'agisse sur
    le parcours en cours.
    """
    task = session.task
    outcome = session.outcome or FocusSession.Outcome.NO_TASK
    reason = {
        FocusSession.Outcome.COMPLETED: "completed",
        FocusSession.Outcome.ALREADY_DONE: "already_done",
        FocusSession.Outcome.NO_TASK: "no_task",
        FocusSession.Outcome.UNDONE: "undone",
    }[outcome]
    task_done = task is not None and task.status == Task.Status.DONE
    return Response({
        "message": "Session terminée.",
        "reason": reason,
        "outcome": outcome,
        "task_completed": task_done,
        "task": TaskSerializer(task).data if task is not None else None,
        "session_id": session.pk,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "cycle": session.completed_cycle,
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def focus_session_complete(request, session_id):
    """Termine la session et enregistre un résultat durable, une seule fois.

    La complétion n'est acceptée que si la session est réellement arrivée au bout,
    d'après l'horloge du serveur :
    - phase "finished" (déjà terminée, y compris après rechargement) ;
    - phase "running" avec échéance dépassée (le client n'a pas encore signalé la fin) ;
    - phase "paused" avec zéro restant.

    Toute tentative prématurée est refusée sans aucun effet sur la tâche.
    Une session déjà traitée (outcome positionné) rejoue le résultat enregistré
    sans nouvel effet métier : répéter /complete/ après une erreur réseau, un
    rechargement ou un second onglet reste sans effet indésirable.
    """
    session = get_object_or_404(FocusSession, pk=session_id)
    now = timezone.now()

    if session.outcome is not None:
        return _focus_completion_response(session)

    if session.phase == FocusSession.Phase.FINISHED:
        expired = True
    elif session.phase == FocusSession.Phase.RUNNING and session.deadline is not None:
        expired = session.deadline <= now
    elif session.phase == FocusSession.Phase.PAUSED:
        expired = session.remaining_time_ms == 0
    else:
        expired = False

    if not expired:
        return Response(
            {"error": "La session n'est pas encore terminée. Laisse le minuteur arriver à zéro avant de marquer la tâche."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    session.phase = FocusSession.Phase.FINISHED
    session.remaining_time_ms = 0
    session.deadline = None
    session.completed_at = now
    # Une session jamais lancée (cycle vide) vaut pour parcours n° 1 : le cycle
    # d'une complétion est toujours défini, pour que toute demande d'annulation
    # s'appuie sur un numéro de parcours concret.
    session.completed_cycle = session.cycle or 1
    session.save(update_fields=["phase", "remaining_time_ms", "deadline", "completed_at", "completed_cycle", "updated_at"])

    task = session.task

    if task is None:
        session.outcome = FocusSession.Outcome.NO_TASK
        session.save(update_fields=["outcome", "updated_at"])
        return _focus_completion_response(session)

    if task.status == Task.Status.DONE:
        session.outcome = FocusSession.Outcome.ALREADY_DONE
        session.save(update_fields=["outcome", "updated_at"])
        return _focus_completion_response(session)

    # Marquage effectif : on garde la version de la tâche au moment du passage
    # pour permettre une annulation sans écraser une modification concurrente.
    task.status = Task.Status.DONE
    task.save(update_fields=["status", "updated_at"])
    session.marked_task_version = task.updated_at
    session.outcome = FocusSession.Outcome.COMPLETED
    session.save(update_fields=["outcome", "marked_task_version", "updated_at"])
    return _focus_completion_response(session)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def focus_session_undo(request, session_id):
    """Annule le marquage effectué par une session, de façon durable.

    Seule une session dont le résultat enregistré est "completed" (c'est-à-dire
    qui a réellement fait passer la tâche de "à faire" à "fait") peut être
    annulée. L'annulation vérifie que la tâche n'a pas changé depuis le marquage :
    en cas de modification concurrente, elle est refusée, l'état existant n'est
    jamais écrasé silencieusement. Après annulation, un rappel de /complete/ ne
    remarquera pas la tâche : le résultat "undone" est rejoué tel quel.
    """
    session = get_object_or_404(FocusSession, pk=session_id)

    if session.outcome != FocusSession.Outcome.COMPLETED:
        return Response(
            {"error": "Rien à annuler : cette session n'a pas fait passer de tâche de « à faire » à « fait »."},
            status=status.HTTP_409_CONFLICT,
        )

    requested_cycle = request.data.get("cycle") if isinstance(request.data, dict) else None
    if requested_cycle is None or requested_cycle != session.completed_cycle:
        return Response(
            {"error": "Cette demande d'annulation correspond à un parcours antérieur de la session : elle est ignorée."},
            status=status.HTTP_409_CONFLICT,
        )

    task = session.task
    if task is None:
        return Response(
            {"error": "La tâche liée à cette session a été supprimée : impossible d'annuler son marquage."},
            status=status.HTTP_409_CONFLICT,
        )

    if task.status != Task.Status.DONE:
        return Response(
            {"error": "La tâche n'est plus marquée comme faite : rien à annuler."},
            status=status.HTTP_409_CONFLICT,
        )

    if session.marked_task_version is None:
        return Response(
            {"error": "L'annulation est impossible pour cette session : aucune version de tâche enregistrée."},
            status=status.HTTP_409_CONFLICT,
        )

    updated = Task.objects.filter(
        pk=task.pk,
        updated_at=session.marked_task_version,
        status=Task.Status.DONE,
    ).update(status=Task.Status.TODO, updated_at=timezone.now())
    if not updated:
        return Response(
            {"error": "La tâche a changé depuis son marquage : annulation refusée pour ne pas écraser cette modification."},
            status=status.HTTP_409_CONFLICT,
        )

    task.refresh_from_db()
    session.outcome = FocusSession.Outcome.UNDONE
    session.save(update_fields=["outcome", "updated_at"])

    return Response({
        "message": "Marquage annulé : la tâche est de nouveau « à faire ».",
        "reason": "undone",
        "outcome": FocusSession.Outcome.UNDONE,
        "task_completed": False,
        "task": TaskSerializer(task).data,
        "session_id": session.pk,
    })


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def briefing_view(request):
    """API du briefing iCloud (lecture seule).

    - ``GET`` : données structurées (agenda + mails récents) ;
    - ``POST`` : texte du point sur la journée (même rendu que la commande chat).

    Si ``BRIEFING_API_KEY`` est définie dans l'environnement, cette API exige
    un jeton (``Authorization: Bearer <clé>`` ou ``X-Briefing-Key``) : elle
    sert de base à un futur accès iPhone authentifié. Elle ne doit jamais être
    exposée directement sur Internet (voir ``backend/briefing/README.md``).
    """
    if not _briefing_authorized(request):
        return Response(
            {"error": "Accès briefing refusé."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if request.method == "GET":
        return Response(structured_briefing())
    return Response({"text": provide_daily_briefing()})


def _briefing_authorized(request) -> bool:
    """Vérifie la clé API du briefing (comparaison en temps constant).

    Sans clé configurée, l'accès reste ouvert comme le reste de l'API de dev
    local ; dès qu'une clé est définie dans l'environnement, elle devient
    obligatoire.
    """
    expected = getattr(settings, "BRIEFING_API_KEY", "") or ""
    if not expected:
        return True
    provided = ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        provided = auth[7:].strip()
    if not provided:
        provided = request.headers.get("X-Briefing-Key", "")
    return bool(provided) and secrets.compare_digest(provided, expected)


# --- API du briefing iCloud ------------------------------------------------


def _get_or_create_conversation(conversation_id=None):
    if conversation_id is None:
        return Conversation.objects.create()
    
    return get_object_or_404(
        Conversation,
        pk=conversation_id,
    )


def _load_history(conversation):
    messages = conversation.messages.order_by("-created_at", "-id")[:HISTORY_LIMIT]
    messages = reversed(list(messages))
    return [
        {"role": message.role, "content": message.content}
        for message in messages
    ]


def _make_auto_title(content):
    normalized = " ".join(content.split())
    if len(normalized) <= AUTO_TITLE_MAX:
        return normalized
    return normalized[: AUTO_TITLE_MAX - 3].rstrip() + "…"


def _update_auto_title(conversation, user_message):
    if conversation.title != DEFAULT_TITLE:
        return
    conversation.title = _make_auto_title(user_message)
    conversation.save(update_fields=["title"])


@transaction.atomic
def _save_messages(conversation, user_message, reply):
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=user_message,
    )
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=reply,
    )

    _update_auto_title(conversation, user_message)
    conversation.save(update_fields=["updated_at"])


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def transcribe(request):
    audio = request.FILES.get("audio")
    if audio is None:
        return Response(
            {"error": "Aucun fichier audio fourni."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if audio.size > settings.AUDIO_MAX_SIZE:
        return Response(
            {"error": "Le fichier audio est trop volumineux."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    fd, temp_path = tempfile.mkstemp(suffix=".audio")
    try:
        with os.fdopen(fd, "wb") as destination:
            for chunk in audio.chunks():
                destination.write(chunk)

        try:
            duration = get_audio_duration(temp_path)
        except TranscriptionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if duration > settings.AUDIO_MAX_DURATION:
            return Response(
                {"error": "L'enregistrement est trop long."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            text = transcribe_audio(temp_path, language=settings.WHISPER_LANGUAGE)
        except TranscriptionUnavailableError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except TranscriptionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response({"text": text})
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@transaction.atomic
def _resolve_confirm(proposal_id):
    updated = ActionProposal.objects.filter(
        pk=proposal_id,
        status=ActionProposal.Status.PENDING,
    ).update(status=ActionProposal.Status.CONFIRMED)

    proposal = get_object_or_404(ActionProposal, pk=proposal_id)

    if not updated:
        return (
            proposal,
            proposal.status == ActionProposal.Status.CONFIRMED,
        )

    if not isinstance(proposal.data, dict):
        raise ValidationError(
            {"error": "Données de proposition invalides."}
        )

    if proposal.action == ActionProposal.Action.SAVE_MEMORY:
        content = proposal.data.get("content")

        if not isinstance(content, str):
            raise ValidationError(
                {"error": "Le texte de la préférence est invalide."}
            )

        if not content.strip() or len(content) > 500:
            raise ValidationError(
                {"error": "La préférence doit contenir entre 1 et 500 caractères."}
            )

        proposal.memory = Memory.objects.create(content=content)
        proposal.save(update_fields=["memory", "updated_at"])

    elif proposal.action == ActionProposal.Action.CREATE_TASK:
        serializer = TaskSerializer(data={
            "title": proposal.data.get("title"),
            "description": proposal.data.get("description", ""),
        })
        serializer.is_valid(raise_exception=True)

        proposal.task = serializer.save()
        proposal.save(update_fields=["task", "updated_at"])

    else:
        raise ValidationError(
            {"error": "Type de proposition non pris en charge."}
        )

    return proposal, True


@transaction.atomic
def _resolve_cancel(proposal_id):
    ActionProposal.objects.filter(
        pk=proposal_id,
        status=ActionProposal.Status.PENDING,
    ).update(status=ActionProposal.Status.CANCELLED)

    proposal = get_object_or_404(ActionProposal, pk=proposal_id)

    return (
        proposal,
        proposal.status == ActionProposal.Status.CANCELLED,
    )


@transaction.atomic
def _create_memory_proposal_turn(conversation, user_message, content):
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=user_message,
    )
    assistant_message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=(
            "Veux-tu que je retienne cette préférence ? "
            "Tu peux choisir Retenir ou Pas maintenant sous ma réponse."
        ),
    )
    proposal = ActionProposal.objects.create(
        conversation=conversation,
        assistant_message=assistant_message,
        action=ActionProposal.Action.SAVE_MEMORY,
        data={"content": content},
    )
    _update_auto_title(conversation, user_message)
    conversation.save(update_fields=["updated_at"])
    return proposal


def _run_action_analysis(message):
    try:
        return parse_task_request(message)
    except InvalidTaskRequest as exc:
        raise ValidationError({"error": str(exc)}) from exc


def _run_reminder_analysis(message):
    try:
        return parse_reminder_request(message)
    except InvalidReminderRequest as exc:
        raise ValidationError({"error": str(exc)}) from exc


@transaction.atomic
def _create_task_direct(conversation, user_message, analysis):
    """Crée la tâche immédiatement (action Jarvis : zéro confirmation)."""
    serializer = TaskSerializer(data=analysis["data"])
    serializer.is_valid(raise_exception=True)
    task = serializer.save()
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_message,
    )
    assistant_message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=f"✅ Tâche ajoutée : {task.title}. Retrouve-la dans l'onglet Tâches.",
    )
    _update_auto_title(conversation, user_message)
    conversation.save(update_fields=["updated_at"])
    return assistant_message, task


@transaction.atomic
def _create_reminder_direct(conversation, user_message, analysis):
    """Crée le rappel et calcule son échéance immédiatement (zéro confirmation)."""
    data = analysis["data"]
    title = data["title"]
    due_at = interpret_when(data.get("when", ""))
    reminder = Reminder.objects.create(title=title, due_at=due_at)
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_message,
    )
    assistant_message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=(
            f"✅ C'est noté : je te rappellerai « {title} » "
            f"le {due_at:%d/%m} à {due_at:%H:%M}."
        ),
    )
    _update_auto_title(conversation, user_message)
    conversation.save(update_fields=["updated_at"])
    return assistant_message, reminder