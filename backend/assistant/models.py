from django.db import models


class Conversation(models.Model):
    title = models.CharField(
        max_length=200,
        default="Nouvelle conversation",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.title} ({self.pk})"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Utilisateur"
        ASSISTANT = "assistant", "MIA"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_role_display()} : {self.content[:60]}"


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "À faire"
        DONE = "done", "Fait"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class ActionProposal(models.Model):
    class Action(models.TextChoices):
        CREATE_TASK = "create_task", "Créer une tâche"
        SAVE_MEMORY = "save_memory", "Retenir une préférence"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        CONFIRMED = "confirmed", "Confirmée"
        CANCELLED = "cancelled", "Annulée"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="action_proposals",
    )
    assistant_message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name="action_proposal",
    )
    action = models.CharField(
        max_length=30,
        choices=Action.choices,
    )
    data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    task = models.OneToOneField(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal",
    )
    memory = models.OneToOneField(
        "Memory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_action_display()} : {self.status}"


class Memory(models.Model):
    content = models.CharField(max_length=500)
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-confirmed_at", "-id"]
        verbose_name = "Préférence mémorisée"
        verbose_name_plural = "Préférences mémorisées"

    def __str__(self):
        return self.content[:80]


class FocusSession(models.Model):
    """
    Session de concentration liée éventuellement à une tâche.
    """
    class Phase(models.TextChoices):
        IDLE = "idle", "Prête"
        RUNNING = "running", "En cours"
        PAUSED = "paused", "En pause"
        FINISHED = "finished", "Terminée"

    class Outcome(models.TextChoices):
        COMPLETED = "completed", "Marquée faite"
        UNDONE = "undone", "Marquage annulé"
        ALREADY_DONE = "already_done", "Déjà faite"
        NO_TASK = "no_task", "Aucune tâche liée"

    # Informations de base de la session
    duration_minutes = models.PositiveIntegerField()
    label = models.CharField(max_length=200, blank=True)
    phase = models.CharField(max_length=20, choices=Phase.choices, default=Phase.IDLE)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Référence à une tâche (optionnelle)
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="focus_sessions"
    )

    # Données de gestion du temps (remplis quand une session est lancée/suivie)
    deadline = models.DateTimeField(null=True, blank=True)
    remaining_time_ms = models.PositiveIntegerField(null=True, blank=True)

    # Résultat durable : la session a-t-elle été traitée, et comment ?
    # Défini une seule fois par le endpoint /complete/, puis rejoué sans nouvel
    # effet (idempotence). 'undone' signifie que le marquage a été annulé.
    outcome = models.CharField(max_length=20, choices=Outcome.choices, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Numéro du parcours courant (incrémenté à chaque nouveau lancé après
    # reset) et numéro du parcours au moment de la dernière complétion :
    # permet d'ignorer les requêtes d'un ancien parcours rejouées plus tard.
    cycle = models.PositiveIntegerField(null=True, blank=True)
    completed_cycle = models.PositiveIntegerField(null=True, blank=True)
    # Version (updated_at) de la tâche au moment du marquage : permet d'éviter
    # d'écraser une modification concurrente lors de l'annulation.
    marked_task_version = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Session de concentration - {self.label or 'Sans titre'}"
