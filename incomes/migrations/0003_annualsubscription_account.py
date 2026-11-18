import django.db.models.deletion
from django.db import migrations, models


def assign_single_account_subscriptions(apps, schema_editor):
    AnnualSubscription = apps.get_model('incomes', 'AnnualSubscription')
    SavingsAccount = apps.get_model('groupcore', 'SavingsAccount')
    for subscription in AnnualSubscription.objects.filter(account__isnull=True).iterator():
        account_ids = list(
            SavingsAccount.objects.filter(owner_id=subscription.member_id)
            .values_list('id', flat=True)[:2]
        )
        if len(account_ids) == 1:
            subscription.account_id = account_ids[0]
            subscription.save(update_fields=['account'])


class Migration(migrations.Migration):
    dependencies = [
        ('groupcore', '0016_memberprofile_welcome_email_attempted_at'),
        ('incomes', '0002_sharecontribution_annualsubscription_welfareledger'),
    ]

    operations = [
        migrations.AddField(
            model_name='annualsubscription',
            name='account',
            field=models.ForeignKey(
                blank=True,
                help_text='Legacy records may remain unassigned until reviewed by the Treasurer.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='annual_subscriptions',
                to='groupcore.savingsaccount',
            ),
        ),
        migrations.RunPython(
            assign_single_account_subscriptions,
            migrations.RunPython.noop,
        ),
        migrations.AlterUniqueTogether(
            name='annualsubscription',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='annualsubscription',
            constraint=models.UniqueConstraint(
                fields=('account', 'year'),
                name='unique_annual_subscription_per_account_year',
            ),
        ),
    ]
