from django.db import migrations, models
import django.db.models.deletion


def backfill_selected_loans(apps, schema_editor):
    DepositSubmission = apps.get_model('deposits', 'DepositSubmission')
    for deposit in DepositSubmission.objects.filter(loan_repayment_amount__gt=0).iterator():
        loan_ids = list(
            deposit.generated_loan_repayments.values_list('loan_id', flat=True).distinct()[:2]
        )
        if len(loan_ids) == 1:
            deposit.loan_repayment_loan_id = loan_ids[0]
            deposit.save(update_fields=['loan_repayment_loan'])


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0014_depositwelfareallocation'),
        ('loans', '0008_loanrepayment_source_deposit'),
    ]

    operations = [
        migrations.AddField(
            model_name='depositsubmission',
            name='loan_repayment_loan',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deposit_repayments', to='loans.loanrequest'),
        ),
        migrations.RunPython(backfill_selected_loans, migrations.RunPython.noop),
    ]
