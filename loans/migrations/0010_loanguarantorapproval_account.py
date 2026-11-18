import django.db.models.deletion
from django.db import migrations, models


def assign_single_guarantor_account(apps, schema_editor):
    LoanGuarantorApproval = apps.get_model('loans', 'LoanGuarantorApproval')
    SavingsAccount = apps.get_model('groupcore', 'SavingsAccount')
    for approval in LoanGuarantorApproval.objects.filter(account__isnull=True).iterator():
        account_ids = list(
            SavingsAccount.objects.filter(owner_id=approval.guarantor_id)
            .values_list('id', flat=True)[:2]
        )
        if len(account_ids) == 1:
            approval.account_id = account_ids[0]
            approval.save(update_fields=['account'])


class Migration(migrations.Migration):
    dependencies = [
        ('groupcore', '0016_memberprofile_welcome_email_attempted_at'),
        ('loans', '0009_settlement_fields_and_repayment_components'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanguarantorapproval',
            name='account',
            field=models.ForeignKey(
                blank=True,
                help_text='Savings account pledged for this guarantee.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='loan_guarantee_approvals',
                to='groupcore.savingsaccount',
            ),
        ),
        migrations.RunPython(
            assign_single_guarantor_account,
            migrations.RunPython.noop,
        ),
        migrations.AlterUniqueTogether(
            name='loanguarantorapproval',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='loanguarantorapproval',
            constraint=models.UniqueConstraint(
                fields=('loan', 'account'),
                name='unique_guarantor_account_per_loan',
            ),
        ),
    ]
