from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('groupcore', '0012_alter_savingsaccount_options'),
        ('loans', '0009_settlement_fields_and_repayment_components'),
    ]

    operations = [
        migrations.CreateModel(
            name='FinancialYearClose',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveIntegerField(unique=True)),
                ('scheduled_closing_date', models.DateField()),
                ('state', models.CharField(choices=[('OPEN', 'Open'), ('LOCKED_REVIEW', 'Locked — Pending Review'), ('FINALIZED', 'Finalized')], default='OPEN', max_length=20)),
                ('cutoff_at', models.DateTimeField(blank=True, null=True)),
                ('auto_locked', models.BooleanField(default=False)),
                ('finalized_at', models.DateTimeField(blank=True, null=True)),
                ('current_version', models.PositiveIntegerField(default=0)),
                ('needs_regeneration', models.BooleanField(default=False)),
                ('last_correction_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('finalized_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='finalized_financial_years', to=settings.AUTH_USER_MODEL)),
                ('locked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='locked_financial_years', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-year']},
        ),
        migrations.CreateModel(
            name='SettlementVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cutoff_at', models.DateTimeField()),
                ('total_savings', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('collected_interest_pool', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('total_payout', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('total_group_loss', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_settlement_versions', to=settings.AUTH_USER_MODEL)),
                ('financial_year', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='versions', to='groupcore.financialyearclose')),
            ],
            options={'ordering': ['-version']},
        ),
        migrations.CreateModel(
            name='FinancialYearLoanSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('frozen_balance', models.DecimalField(decimal_places=2, max_digits=16)),
                ('collected_interest', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('frozen_at', models.DateTimeField()),
                ('financial_year', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='loan_snapshots', to='groupcore.financialyearclose')),
                ('loan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='year_end_snapshots', to='loans.loanrequest')),
            ],
        ),
        migrations.CreateModel(
            name='AccountSettlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('savings_total', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('interest_share', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('welfare_due', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('fine_due', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('annual_due', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('borrower_loan_offset', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('guarantor_offset', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('gross_payout', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('net_payout', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('payout_status', models.CharField(choices=[('UNPAID', 'Unpaid'), ('PARTIAL', 'Partially Paid'), ('PAID', 'Paid')], default='UNPAID', max_length=10)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='settlements', to='groupcore.savingsaccount')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='account_settlements', to=settings.AUTH_USER_MODEL)),
                ('settlement_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='account_settlements', to='groupcore.settlementversion')),
            ],
            options={'ordering': ['member__first_name', 'member__last_name', 'account__label']},
        ),
        migrations.CreateModel(
            name='SettlementPayoutPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=16)),
                ('paid_on', models.DateField()),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account_settlement', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='payments', to='groupcore.accountsettlement')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recorded_settlement_payouts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['paid_on', 'id']},
        ),
        migrations.CreateModel(
            name='SettlementLoanAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('allocation_type', models.CharField(choices=[('BORROWER', 'Borrower payout offset'), ('GUARANTOR', 'Guarantor payout offset'), ('GROUP_LOSS', 'Group loss')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=16)),
                ('note', models.TextField(blank=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='settlement_loan_allocations', to='groupcore.savingsaccount')),
                ('loan_snapshot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='allocations', to='groupcore.financialyearloansnapshot')),
                ('member', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='settlement_loan_allocations', to=settings.AUTH_USER_MODEL)),
                ('settlement_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='loan_allocations', to='groupcore.settlementversion')),
            ],
            options={'ordering': ['loan_snapshot_id', 'id']},
        ),
        migrations.AddConstraint(
            model_name='settlementversion',
            constraint=models.UniqueConstraint(fields=('financial_year', 'version'), name='unique_financial_year_settlement_version'),
        ),
        migrations.AddConstraint(
            model_name='financialyearloansnapshot',
            constraint=models.UniqueConstraint(fields=('financial_year', 'loan'), name='unique_financial_year_loan_snapshot'),
        ),
        migrations.AddConstraint(
            model_name='accountsettlement',
            constraint=models.UniqueConstraint(fields=('settlement_version', 'account'), name='unique_account_per_settlement_version'),
        ),
    ]
