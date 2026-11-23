import json
import os
import tempfile

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from .models import ActionProposal, Conversation, Memory, Message, Task
from .serializers import (
    ActionProposalSerializer,
    MemorySerializer,
    ChatRequestSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    ConversationUpdateSerializer,
    TaskSerializer,
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
def task_detail(request, task_id):
    task = get_object_or_404(Task, pk=task_id)

    if request.method == "PATCH":
        serializer = TaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(TaskSerializer(task).data)

    task.delete()
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

    analysis = _run_action_analysis(message)

    if analysis.get("action") == "create_task":
        proposal = _create_proposal_turn(conversation, message, analysis)
        return Response(
            {
                "conversation_id": conversation.pk,
                "action_proposal": ActionProposalSerializer(proposal).data,
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

            analysis = _run_action_analysis(message)
            if analysis.get("action") == "create_task":
                proposal = _create_proposal_turn(conversation, message, analysis)
                yield _encode_stream_event("delta", content=proposal.assistant_message.content)
                yield _encode_stream_event(
                    "done",
                    conversation_id=conversation_id,
                    action_proposal=ActionProposalSerializer(proposal).data,
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



def _run_action_analysis(message):
    try:
        return parse_task_request(message)
    except InvalidTaskRequest as exc:
        raise ValidationError({"error": str(exc)}) from exc


@transaction.atomic
def _create_proposal_turn(conversation, user_message, analysis):
    serializer = TaskSerializer(data=analysis["data"])
    serializer.is_valid(raise_exception=True)
    data = {
        "title": serializer.validated_data["title"],
        "description": serializer.validated_data.get("description", ""),
    }
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_message,
    )
    assistant_message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=(
            f"Je te propose d'ajouter la tâche : {data['title']}. "
            "Choisis Ajouter ou Annuler sous ma réponse. Rien n'est encore ajouté."
        ),
    )
    proposal = ActionProposal.objects.create(
        conversation=conversation,
        assistant_message=assistant_message,
        action=ActionProposal.Action.CREATE_TASK,
        data=data,
    )
    _update_auto_title(conversation, user_message)
    conversation.save(update_fields=["updated_at"])
    return proposal
