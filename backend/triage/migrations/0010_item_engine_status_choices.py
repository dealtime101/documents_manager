import logging

from django.db import migrations, models

log = logging.getLogger(__name__)
KNOWN = ('auto', 'confirm', 'manual', 'duplicate', 'logical_duplicate', 'error')


def repair(apps, schema_editor):
    """A row written before the list was closed could hold another value: it becomes 'manual' (a human decides) BEFORE the
    constraint is added, so that adding it cannot fail on an existing database. The value it held is lost by the update (this
    cannot be reversed), so what was found is logged first: which values, and how many rows each."""
    marks = ", ".join("%s" for _ in KNOWN)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT engine_status, COUNT(*) FROM triage_item WHERE engine_status NOT IN ({marks}) GROUP BY engine_status", KNOWN)
        found = cursor.fetchall()
        for value, count in found:
            log.warning("triage_item.engine_status: %d row(s) held the unknown value %r; they become 'manual' (the old value is not kept)",
                        count, value)
        if found:
            cursor.execute(f"UPDATE triage_item SET engine_status = 'manual' WHERE engine_status NOT IN ({marks})", KNOWN)


class Migration(migrations.Migration):

    dependencies = [
        ('triage', '0009_scanjob_counters_bounded'),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
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
