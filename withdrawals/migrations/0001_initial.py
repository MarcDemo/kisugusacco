import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('groupcore', '0016_memberprofile_welcome_email_attempted_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Withdrawal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('withdrawn_on', models.DateField()),
                ('reason', models.TextField()),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('is_voided', models.BooleanField(default=False)),
                ('void_reason', models.TextField(blank=True)),
                ('voided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='withdrawals', to='groupcore.savingsaccount')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='savings_withdrawals', to=settings.AUTH_USER_MODEL)),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recorded_withdrawals', to=settings.AUTH_USER_MODEL)),
                ('voided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='voided_withdrawals', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-withdrawn_on', '-id']},
        ),
        migrations.CreateModel(
            name='WithdrawalRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('revision_number', models.PositiveIntegerField()),
                ('before_data', models.JSONField()),
                ('after_data', models.JSONField()),
                ('reason', models.TextField()),
                ('edited_at', models.DateTimeField(auto_now_add=True)),
                ('edited_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='withdrawal_revisions', to=settings.AUTH_USER_MODEL)),
                ('withdrawal', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='revisions', to='withdrawals.withdrawal')),
            ],
            options={'ordering': ['revision_number', 'id']},
        ),
        migrations.AddConstraint(
            model_name='withdrawal',
            constraint=models.CheckConstraint(condition=models.Q(('amount__gt', 0)), name='withdrawal_amount_positive'),
        ),
        migrations.AddConstraint(
            model_name='withdrawalrevision',
            constraint=models.UniqueConstraint(fields=('withdrawal', 'revision_number'), name='unique_withdrawal_revision_number'),
        ),
    ]

