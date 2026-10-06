from django.db import migrations, models

# A row written before the list was closed could hold another value: it becomes 'manual' (a human decides) BEFORE the
# constraint is added, so that adding it cannot fail on an existing database.
REPAIR = """
UPDATE triage_item SET engine_status = 'manual'
WHERE engine_status NOT IN ('auto', 'confirm', 'manual', 'duplicate', 'logical_duplicate', 'error');
"""


class Migration(migrations.Migration):

    dependencies = [
        ('triage', '0009_scanjob_counters_bounded'),
    ]

    operations = [
        migrations.RunSQL(REPAIR, reverse_sql=migrations.RunSQL.noop),
        migrations.AlterField(
            model_name='item',
            name='engine_status',
            field=models.CharField(
                choices=[('auto', 'Auto'), ('confirm', 'Confirm'), ('manual', 'Manual'), ('duplicate', 'Duplicate'),
                         ('logical_duplicate', 'Logical Duplicate'), ('error', 'Error')], max_length=20),
        ),
        migrations.AddConstraint(
            model_name='item',
            constraint=models.CheckConstraint(
                condition=models.Q(('engine_status__in', ['auto', 'confirm', 'manual', 'duplicate', 'logical_duplicate', 'error'])),
                name='item_engine_status_is_known'),
        ),
    ]
