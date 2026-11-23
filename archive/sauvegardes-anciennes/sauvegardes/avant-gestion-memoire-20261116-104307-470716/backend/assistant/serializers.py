from rest_framework import serializers

from .models import ActionProposal, Conversation, Memory, Message, Task


class ChatRequestSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    message = serializers.CharField(
        max_length=4000,
        allow_blank=False,
        trim_whitespace=True,
    )


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "updated_at"]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "created_at", "updated_at"]

class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Memory
        fields = ["id", "content", "confirmed_at"]
        read_only_fields = ["id", "content", "confirmed_at"]

class ActionProposalSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)
    memory = MemorySerializer(read_only=True)

    class Meta:
        model = ActionProposal
        fields = [
            "id",
            "assistant_message_id",
            "action",
            "data",
            "status",
            "task",
            "memory",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    action_proposals = ActionProposalSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages", "action_proposals"]


class ConversationUpdateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(required=True)

    class Meta:
        model = Conversation
        fields = ["title"]

    def validate_title(self, value):
        title = value.strip()
        if not title:
            raise serializers.ValidationError("Le titre ne peut pas être vide.")
        if len(title) > 200:
            raise serializers.ValidationError("Le titre est trop long.")
        return title
