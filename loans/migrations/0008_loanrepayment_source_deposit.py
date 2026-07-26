from django.db import migrations, models
import django.db.models.deletion


def link_source_deposits(apps, schema_editor):
    LoanRepayment = apps.get_model('loans', 'LoanRepayment')
    DepositSubmission = apps.get_model('deposits', 'DepositSubmission')
    for repayment in LoanRepayment.objects.filter(source_deposit__isnull=True).iterator():
        notes = repayment.notes or ''
        marker = 'Deposit #'
        if marker not in notes:
            continue
        suffix = notes.split(marker, 1)[1].split(')', 1)[0].strip()
        if suffix.isdigit() and DepositSubmission.objects.filter(pk=int(suffix)).exists():
            LoanRepayment.objects.filter(pk=repayment.pk).update(source_deposit_id=int(suffix))


class Migration(migrations.Migration):
    dependencies = [
        ('loans', '0007_loan_approval_audit'),
        ('deposits', '0014_depositwelfareallocation'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrepayment',
            name='source_deposit',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='generated_loan_repayments', to='deposits.depositsubmission'),
        ),
        migrations.RunPython(link_source_deposits, migrations.RunPython.noop),
    ]
