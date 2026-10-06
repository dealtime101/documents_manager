from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('triage', '0004_one_running_scan_and_pending_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='source_size',
            field=models.BigIntegerField(null=True),
        ),
        migrations.AddField(
            model_name='item',
            name='source_mtime_ns',
            field=models.BigIntegerField(null=True),
        ),
    ]
