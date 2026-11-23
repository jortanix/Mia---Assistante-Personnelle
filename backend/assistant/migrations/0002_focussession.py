# Generated migration
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        # FocusSession lie une tâche (FK SET_NULL) : Task n'existe qu'à partir
        # de 0002_task_actionproposal. Sans cette dépendance, le migrate échoue
        # sur une base fraîche (table assistant_task inexistante).
        ('assistant', '0002_task_actionproposal'),
    ]

    operations = [
        migrations.CreateModel(
            name='FocusSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('duration_minutes', models.PositiveIntegerField()),
                ('label', models.CharField(blank=True, max_length=200)),
                ('phase', models.CharField(choices=[('idle', 'Prête'), ('running', 'En cours'), ('paused', 'En pause'), ('finished', 'Terminée')], default='idle', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deadline', models.DateTimeField(blank=True, null=True)),
                ('remaining_time_ms', models.PositiveIntegerField()),
                ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='focus_sessions', to='assistant.task')),
            ],
        ),
    ]