from datetime import date, timedelta

from django.db import migrations
from django.utils import timezone


def second_friday_of_december(year):
    december_first = date(year, 12, 1)
    first_friday_offset = (4 - december_first.weekday()) % 7
    return december_first + timedelta(days=first_friday_offset + 7)


def void_post_closing_fines(apps, schema_editor):
    Fine = apps.get_model('fines', 'Fine')
    now = timezone.now()
    for fine in Fine.objects.filter(
        fine_type='MISSED_WEEKLY_SAVING',
        reference_week__isnull=False,
        is_voided=False,
    ).iterator():
        if fine.reference_week > second_friday_of_december(fine.reference_week.year):
            fine.is_voided = True
            fine.voided_on = now
            fine.voided_reason = (
                'Voided because the referenced week falls after the saving year '
                'closed on the second Friday of December.'
            )
            fine.save(update_fields=['is_voided', 'voided_on', 'voided_reason'])


class Migration(migrations.Migration):

    dependencies = [
        ('fines', '0006_fine_void_fields'),
    ]

    operations = [
        migrations.RunPython(void_post_closing_fines, migrations.RunPython.noop),
    ]
