from django.urls import path

from .views import (
    memory_list,
    memory_detail,
    chat,
    chat_stream,
    conversation_detail,
    conversation_list,
    transcribe,
    action_proposal_confirm,
    action_proposal_cancel,
)


urlpatterns = [
    path("conversations/", conversation_list, name="conversation-list"),
    path(
        "conversations/<int:conversation_id>/",
        conversation_detail,
        name="conversation-detail",
    ),
    path("chat/", chat, name="chat"),
    path("chat/stream/", chat_stream, name="chat-stream"),
    path("audio/transcribe/", transcribe, name="audio-transcribe"),
    path(
        "action-proposals/<int:proposal_id>/confirm/",
        action_proposal_confirm,
        name="action-proposal-confirm",
    ),
    path(
        "action-proposals/<int:proposal_id>/cancel/",
        action_proposal_cancel,
        name="action-proposal-cancel",
    ),
    path("memories/", memory_list, name="memory-list"),
    path("memories/<int:memory_id>/", memory_detail, name="memory-detail"),
]
