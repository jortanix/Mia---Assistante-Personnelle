# Rend remaining_time_ms optionnel : facultatif à la création, rempli quand
# une session est lancée ou suivie côté client.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assistant', '0002_focussession'),
    ]

    operations = [
        migrations.AlterField(
            model_name='focussession',
            name='remaining_time_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
