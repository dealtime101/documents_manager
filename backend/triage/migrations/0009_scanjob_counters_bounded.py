from django.db import migrations, models

# Existing rows are brought inside the bounds FIRST, so that adding the constraints cannot fail on a database that was
# written before they existed (the counters were never checked).
REPAIR = """
UPDATE triage_scanjob SET total = MAX(total, 0), done = MAX(done, 0), created = MAX(created, 0), skipped = MAX(skipped, 0);
UPDATE triage_scanjob SET done = MIN(done, total);
UPDATE triage_scanjob SET created = MIN(created, done);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('triage', '0008_item_text_search'),
    ]

    operations = [
        migrations.RunSQL(REPAIR, reverse_sql=migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name='scanjob',
            constraint=models.CheckConstraint(
                condition=models.Q(total__gte=0, done__gte=0, created__gte=0, skipped__gte=0),
                name='scan_counters_not_negative'),
        ),
        migrations.AddConstraint(
            model_name='scanjob',
            constraint=models.CheckConstraint(
                condition=models.Q(done__lte=models.F('total'), created__lte=models.F('done')),
                name='scan_counters_in_order'),
        ),
    ]
