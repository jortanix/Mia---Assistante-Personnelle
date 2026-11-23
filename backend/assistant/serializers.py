from rest_framework import serializers
from .models import ActionProposal, Conversation, Memory, Message, Task, FocusSession


class ChatRequestSerializer(serializers.Serializer):
    use_memory = serializers.BooleanField(required=False, default=False)
    conversation_id = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    message = serializers.CharField(
        max_length=4000,
        allow_blank=False,
        trim_whitespace=True,
    )


class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Memory
        fields = [
            "id",
            "content",
            "confirmed_at",
        ]


class TaskSerializer(serializers.ModelSerializer):
    title = serializers.CharField(
        max_length=200,
        allow_blank=False,
        trim_whitespace=True,
    )
    description = serializers.CharField(
        max_length=2000,
        allow_blank=True,
        required=False,
        default="",
    )

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "status",
            "created_at",
            "updated_at",
        ]


class TaskListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "status",
            "created_at",
            "updated_at",
        ]


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


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "title",
            "created_at",
            "updated_at",
        ]


class ConversationDetailSerializer(serializers.ModelSerializer):
    messages = serializers.SerializerMethodField()
    action_proposals = ActionProposalSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id",
            "title",
            "created_at",
            "updated_at",
            "messages",
            "action_proposals",
        ]

    def get_messages(self, obj):
        messages = obj.messages.order_by("created_at", "id")
        return MessageSerializer(messages, many=True).data


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


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "created_at",
        ]


class FocusSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FocusSession
        fields = [
            "id",
            "duration_minutes",
            "label",
            "phase",
            "deadline",
            "remaining_time_ms",
            "outcome",
            "completed_at",
            "cycle",
            "completed_cycle",
            "created_at",
            "updated_at",
            "task",
        ]
        
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.task:
            data["task"] = TaskSerializer(instance.task).data
        return data


class FocusSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FocusSession
        fields = [
            "duration_minutes",
            "label",
            "task",
        ]


class FocusSessionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FocusSession
        fields = [
            "duration_minutes",
            "label",
        ]
