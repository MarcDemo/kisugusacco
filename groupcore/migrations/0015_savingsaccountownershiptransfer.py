from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('groupcore', '0014_memberprofile_welcome_email_sent_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SavingsAccountOwnershipTransfer',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('account_label', models.CharField(max_length=100)),
                ('reason', models.TextField()),
                ('source_profile_deactivated', models.BooleanField(default=False)),
                ('transferred_at', models.DateTimeField(auto_now_add=True)),
                (
                    'account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='ownership_transfers',
                        to='groupcore.savingsaccount',
                    ),
                ),
                (
                    'new_owner',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='received_savings_accounts',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'old_owner',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='transferred_savings_accounts',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'transferred_by',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='performed_savings_account_transfers',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['-transferred_at', '-id'],
            },
        ),
    ]
