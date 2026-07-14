from decimal import Decimal

from django.db import migrations, models


def copy_paid_amounts(apps, schema_editor):
    Fine = apps.get_model('fines', 'Fine')
    for fine in Fine.objects.filter(is_paid=True):
        fine.amount_paid = fine.amount
        fine.save(update_fields=['amount_paid'])


def remove_duplicate_weekly_fines(apps, schema_editor):
    Fine = apps.get_model('fines', 'Fine')
    seen = set()
    for fine in Fine.objects.filter(fine_type='MISSED_WEEKLY_SAVING').order_by('id'):
        key = (fine.member_id, fine.account_id, fine.fine_type, fine.reference_week)
        if key in seen:
            fine.delete()
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [('fines', '0003_fine_account')]
    operations = [
        migrations.AddField(
            model_name='fine',
            name='amount_paid',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.RunPython(copy_paid_amounts, migrations.RunPython.noop),
        migrations.RunPython(remove_duplicate_weekly_fines, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='fine',
            constraint=models.UniqueConstraint(
                fields=('member', 'account', 'fine_type', 'reference_week'),
                name='unique_account_weekly_fine',
            ),
        ),
    ]
