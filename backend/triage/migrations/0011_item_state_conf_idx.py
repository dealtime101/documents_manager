from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('triage', '0010_item_engine_status_choices'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='item',
            index=models.Index(fields=['state', '-confidence', 'id'], name='item_state_conf_idx'),
        ),
    ]
