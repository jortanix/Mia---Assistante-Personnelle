from django.urls import path

from .views import (
    task_list,
    task_detail,
    memory_list,
    memory_detail,
    chat,
    chat_stream,
    conversation_detail,
    conversation_list,
    transcribe,
    action_proposal_confirm,
    action_proposal_cancel,
    focus_session_list,
    focus_session_detail,
    focus_session_complete,
    focus_session_undo,
    focus_session_reset,
    briefing_view,
    reminder_list,
    reminder_detail,
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
    path("briefing/", briefing_view, name="briefing"),
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
    path("tasks/", task_list, name="task-list"),
    path("tasks/<int:task_id>/", task_detail, name="task-detail"),
    path("focus-sessions/", focus_session_list, name="focus-session-list"),
    path("focus-sessions/<int:session_id>/", focus_session_detail, name="focus-session-detail"),
    path("focus-sessions/<int:session_id>/complete/", focus_session_complete, name="focus-session-complete"),
    path("focus-sessions/<int:session_id>/undo/", focus_session_undo, name="focus-session-undo"),
    path("focus-sessions/<int:session_id>/reset/", focus_session_reset, name="focus-session-reset"),
    path("reminders/", reminder_list, name="reminder-list"),
    path("reminders/<int:reminder_id>/", reminder_detail, name="reminder-detail"),
]
