import json

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from unittest.mock import patch

from .models import Conversation, Message


def _stream_body(response):
    chunks = []
    for chunk in response.streaming_content:
        chunks.append(chunk.decode("utf-8"))
    return "".join(chunks)


def _ndjson(body):
    return [json.loads(line) for line in body.splitlines() if line.strip()]


class ChatStreamEndpointTests(TestCase):
    def _post(self, payload):
        return self.client.post("/api/chat/stream/", payload, content_type="application/json")

    def test_invalid_conversation_id_returns_400(self):
        response = self._post({"conversation_id": "abc", "message": "Bonjour"})
        self.assertEqual(response.status_code, 400)

    def test_missing_message_returns_400(self):
        response = self._post({"message": ""})
        self.assertEqual(response.status_code, 400)

    def test_inexistent_conversation_returns_404(self):
        response = self._post({"conversation_id": 99999, "message": "Bonjour"})
        self.assertEqual(response.status_code, 404)

    @patch("assistant.services.requests.post")
    def test_successful_stream(self, mock_post):
        ollama_lines = [
            {"message": {"content": "Bonjour"}},
            {"message": {"content": " !"}},
            {"message": {"content": " Comment ça va ?"}},
            {"message": {"content": "", "done": True}},
        ]
        mock_post.return_value = _fake_response(
            "\n".join(json.dumps(line) for line in ollama_lines) + "\n"
        )

        response = self._post({"message": "Salut"})
        self.assertEqual(response.status_code, 200)
        body = _stream_body(response)

        events = _ndjson(body)
        self.assertEqual(events[0]["type"], "start")
        self.assertIsInstance(events[0]["conversation_id"], int)

        deltas = [e["content"] for e in events if e["type"] == "delta"]
        self.assertEqual(deltas, ["Bonjour", " !", " Comment ça va ?"])

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["conversation_id"], events[0]["conversation_id"])

    @patch("assistant.services.requests.post")
    def test_messages_saved_exactly_once(self, mock_post):
        ollama_lines = [
            {"message": {"content": "Réponse finale"}},
            {"message": {"content": "", "done": True}},
        ]
        mock_post.return_value = _fake_response(
            "\n".join(json.dumps(line) for line in ollama_lines) + "\n"
        )

        response = self._post({"message": "Question unique"})
        body = _stream_body(response)

        events = _ndjson(body)
        conversation_id = events[0]["conversation_id"]
        self.assertEqual(events[-1]["type"], "done")

        conversation = Conversation.objects.get(pk=conversation_id)
        messages = list(conversation.messages.values_list("role", "content"))
        self.assertEqual(
            messages,
            [
                (Message.Role.USER, "Question unique"),
                (Message.Role.ASSISTANT, "Réponse finale"),
            ],
        )

    def test_error_during_generation(self):
        from assistant.services import OllamaResponseError

        with patch(
            "assistant.views.generate_reply_stream",
            side_effect=_failing_stream(OllamaResponseError("Ollama a planté.")),
        ):
            response = self._post({"message": "Salut"})
            self.assertEqual(response.status_code, 200)
            body = _stream_body(response)

        events = _ndjson(body)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Ollama", events[-1]["message"])
        self.assertNotIn("done", [e["type"] for e in events])


class ChatEndpointTests(TestCase):
    def test_non_streaming_chat_still_works(self):
        with patch("assistant.services.requests.post") as mock_post:
            mock_post.return_value = _fake_response(
                json.dumps({"message": {"content": "Réponse classique"}})
            )
            response = self.client.post(
                "/api/chat/",
                {"message": "Bonjour"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Réponse classique")


class AutoTitleTests(TestCase):
    @patch("assistant.services.requests.post")
    def test_first_message_generates_title(self, mock_post):
        mock_post.return_value = _fake_response(
            json.dumps({"message": {"content": "Réponse"}})
        )
        response = self.client.post(
            "/api/chat/",
            {"message": "Comment organiser une réunion ?"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        conversation = Conversation.objects.get(
            pk=response.json()["conversation_id"]
        )
        self.assertEqual(conversation.title, "Comment organiser une réunion ?")

    @patch("assistant.services.requests.post")
    def test_auto_title_normalizes_spaces(self, mock_post):
        mock_post.return_value = _fake_response(
            json.dumps({"message": {"content": "Réponse"}})
        )
        response = self.client.post(
            "/api/chat/",
            {"message": "   Bonjour   le   monde  "},
            content_type="application/json",
        )
        conversation = Conversation.objects.get(
            pk=response.json()["conversation_id"]
        )
        self.assertEqual(conversation.title, "Bonjour le monde")

    @patch("assistant.services.requests.post")
    def test_auto_title_truncates_and_adds_ellipsis(self, mock_post):
        from assistant.views import AUTO_TITLE_MAX

        mock_post.return_value = _fake_response(
            json.dumps({"message": {"content": "Réponse"}})
        )
        long_message = "a" * 200
        response = self.client.post(
            "/api/chat/",
            {"message": long_message},
            content_type="application/json",
        )
        conversation = Conversation.objects.get(
            pk=response.json()["conversation_id"]
        )
        self.assertTrue(conversation.title.endswith("…"))
        self.assertLessEqual(len(conversation.title), AUTO_TITLE_MAX)

    @patch("assistant.services.requests.post")
    def test_custom_title_not_overwritten(self, mock_post):
        conversation = Conversation.objects.create(title="Titre perso")
        mock_post.return_value = _fake_response(
            json.dumps({"message": {"content": "Réponse"}})
        )
        response = self.client.post(
            "/api/chat/",
            {"conversation_id": conversation.pk, "message": "Nouveau message"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Titre perso")


class ConversationUpdateTests(TestCase):
    def _patch(self, conversation_id, payload):
        return self.client.patch(
            f"/api/conversations/{conversation_id}/",
            payload,
            content_type="application/json",
        )

    def test_valid_rename(self):
        conversation = Conversation.objects.create(title="Ancien titre")
        response = self._patch(conversation.pk, {"title": "  Nouveau titre  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Nouveau titre")

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Nouveau titre")

    def test_blank_title_returns_400(self):
        conversation = Conversation.objects.create(title="Ancien titre")
        response = self._patch(conversation.pk, {"title": "   "})
        self.assertEqual(response.status_code, 400)

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Ancien titre")

    def test_missing_title_returns_400(self):
        conversation = Conversation.objects.create(title="Ancien titre")
        response = self._patch(conversation.pk, {})
        self.assertEqual(response.status_code, 400)

    def test_title_too_long_returns_400(self):
        conversation = Conversation.objects.create(title="Ancien titre")
        response = self._patch(conversation.pk, {"title": "x" * 201})
        self.assertEqual(response.status_code, 400)

    def test_rename_inexistent_returns_404(self):
        response = self._patch(99999, {"title": "Nouveau"})
        self.assertEqual(response.status_code, 404)


class ConversationDeleteTests(TestCase):
    def test_delete_conversation_and_messages(self):
        conversation = Conversation.objects.create(title="À supprimer")
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content="Bonjour",
        )
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content="Salut",
        )
        self.assertEqual(Message.objects.count(), 2)

        response = self.client.delete(f"/api/conversations/{conversation.pk}/")
        self.assertEqual(response.status_code, 204)

        self.assertFalse(Conversation.objects.filter(pk=conversation.pk).exists())
        self.assertEqual(Message.objects.count(), 0)

    def test_delete_inexistent_returns_404(self):
        response = self.client.delete("/api/conversations/99999/")
        self.assertEqual(response.status_code, 404)


def _audio_upload(content=b"fake-audio-bytes", name="clip.webm"):
    return SimpleUploadedFile(name, content, content_type="audio/webm")


class TranscribeEndpointTests(TestCase):
    def _post(self, audio):
        data = {"audio": audio} if audio is not None else {}
        return self.client.post("/api/audio/transcribe/", data)

    @patch("assistant.views.get_audio_duration", return_value=2.0)
    @patch("assistant.views.transcribe_audio", return_value="Bonjour le monde")
    def test_successful_transcription(self, mock_transcribe, mock_duration):
        response = self._post(_audio_upload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "Bonjour le monde"})
        mock_duration.assert_called_once()
        mock_transcribe.assert_called_once()

    def test_missing_file_returns_400(self):
        response = self._post(None)
        self.assertEqual(response.status_code, 400)

    @patch("assistant.views.get_audio_duration", return_value=1.0)
    @patch("assistant.views.transcribe_audio", return_value="texte")
    def test_file_too_large_returns_413(self, mock_transcribe, mock_duration):
        with override_settings(AUDIO_MAX_SIZE=10):
            response = self._post(_audio_upload(content=b"x" * 20))

        self.assertEqual(response.status_code, 413)
        mock_duration.assert_not_called()
        mock_transcribe.assert_not_called()

    @patch("assistant.views.transcribe_audio")
    def test_invalid_audio_returns_400(self, mock_transcribe):
        from assistant.transcription import TranscriptionError

        with patch(
            "assistant.views.get_audio_duration",
            side_effect=TranscriptionError("Le fichier audio est invalide."),
        ):
            response = self._post(_audio_upload())

        self.assertEqual(response.status_code, 400)
        mock_transcribe.assert_not_called()

    @patch("assistant.views.transcribe_audio")
    def test_excessive_duration_returns_422(self, mock_transcribe):
        with patch("assistant.views.get_audio_duration", return_value=999.0):
            response = self._post(_audio_upload())

        self.assertEqual(response.status_code, 422)
        mock_transcribe.assert_not_called()

    @patch("assistant.views.get_audio_duration", return_value=1.0)
    def test_no_speech_returns_422(self, mock_duration):
        from assistant.transcription import TranscriptionError

        with patch(
            "assistant.views.transcribe_audio",
            side_effect=TranscriptionError("Aucune parole n'a été détectée."),
        ):
            response = self._post(_audio_upload())

        self.assertEqual(response.status_code, 422)

    @patch("assistant.views.get_audio_duration", return_value=1.0)
    def test_engine_unavailable_returns_503(self, mock_duration):
        from assistant.transcription import TranscriptionUnavailableError

        with patch(
            "assistant.views.transcribe_audio",
            side_effect=TranscriptionUnavailableError("Moteur indisponible."),
        ):
            response = self._post(_audio_upload())

        self.assertEqual(response.status_code, 503)

    @patch("assistant.views.get_audio_duration", return_value=1.0)
    @patch("assistant.views.transcribe_audio", return_value="texte")
    def test_temporary_file_is_removed(self, mock_transcribe, mock_duration):
        response = self._post(_audio_upload())
        self.assertEqual(response.status_code, 200)



class _FakeRequestsResponse:
    def __init__(self, text):
        self._text = text
        self.status_code = 200

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        for line in self._text.splitlines():
            yield line.encode("utf-8")

    def json(self):
        return json.loads(self._text)

    def close(self):
        return None


def _fake_response(text):
    return _FakeRequestsResponse(text)


def _failing_stream(exc):
    def generator(*args, **kwargs):
        yield "delta", "partiel"
        raise exc

    return generator
