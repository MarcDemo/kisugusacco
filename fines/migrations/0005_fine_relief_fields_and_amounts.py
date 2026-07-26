from datetime import date, timedelta
from decimal import Decimal
from django.db import migrations, models


def second_friday(year):
    first = date(year, 12, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 7)


def recalculate_open_fines(apps, schema_editor):
    Fine = apps.get_model('fines', 'Fine')
    DepositSubmission = apps.get_model('deposits', 'DepositSubmission')
    today = date.today()
    for fine in Fine.objects.filter(fine_type='MISSED_WEEKLY_SAVING', is_paid=False).iterator():
        target = Decimal('2000.00')
        relief_date = None
        reference_week = fine.reference_week
        if reference_week:
            closing = second_friday(reference_week.year)
            if today >= closing and reference_week <= closing:
                paid = Decimal('0.00')
                payments = DepositSubmission.objects.filter(
                    member_id=fine.member_id,
                    account_id=fine.account_id,
                    payment_week=reference_week,
                    payment_date__lte=closing,
                    status__in=['PENDING', 'APPROVED'],
                )
                for deposit in payments:
                    paid += deposit.saving_amount or Decimal('0.00')
                if paid < Decimal('10000.00'):
                    target = Decimal('1000.00')
                    relief_date = closing
        fine.original_amount = Decimal('2000.00') if relief_date else None
        fine.relief_applied_on = relief_date
        fine.amount = max(target, fine.amount_paid or Decimal('0.00'))
        fine.is_paid = fine.amount_paid >= fine.amount
        fine.save(update_fields=['amount', 'original_amount', 'relief_applied_on', 'is_paid'])


class Migration(migrations.Migration):
    dependencies = [
        ('fines', '0004_fine_amount_paid_and_unique'),
        ('deposits', '0015_depositsubmission_loan_repayment_loan'),
    ]

    operations = [
        migrations.AddField(
            model_name='fine',
            name='original_amount',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Amount before permanent year-end relief was applied.', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='fine',
            name='relief_applied_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(recalculate_open_fines, migrations.RunPython.noop),
    ]
