from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0013_depositfineallocation'),
        ('groupcore', '0011_financialrecordrevision'),
    ]

    operations = [
        migrations.CreateModel(
            name='DepositWelfareAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('welfare_week', models.DateField()),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('1000.00'), max_digits=10)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='welfare_allocations', to='groupcore.savingsaccount')),
                ('deposit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='welfare_allocations', to='deposits.depositsubmission')),
            ],
            options={'ordering': ['welfare_week', 'id']},
        ),
        migrations.AddConstraint(
            model_name='depositwelfareallocation',
            constraint=models.UniqueConstraint(fields=('deposit', 'welfare_week'), name='unique_deposit_welfare_week'),
        ),
        migrations.AddConstraint(
            model_name='depositwelfareallocation',
            constraint=models.CheckConstraint(condition=models.Q(('amount', Decimal('1000.00'))), name='welfare_allocation_fixed_amount'),
        ),
    ]
