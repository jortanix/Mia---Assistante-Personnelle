# Résultat durable des sessions de concentration : outcome (completed/undone/
# already_done/no_task), completed_at et la version de la tâche au moment du
# marquage (marked_task_version) pour une annulation sans conflit.
#
# Cette migration dépend des deux feuilles du graphe (branche FocusSession :
# 0003_focussession_remaining_optional ; branche tâches/mémoire :
# 0004_actionproposal_memory...) pour converger vers une feuille unique.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0003_focussession_remaining_optional"),
        ("assistant", "0004_actionproposal_memory_alter_actionproposal_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="focussession",
            name="outcome",
            field=models.CharField(
                blank=True,
                choices=[
                    ("completed", "Marquée faite"),
                    ("undone", "Marquage annulé"),
                    ("already_done", "Déjà faite"),
                    ("no_task", "Aucune tâche liée"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="focussession",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="focussession",
            name="marked_task_version",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
